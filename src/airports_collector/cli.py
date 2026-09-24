from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import httpx

from .collector import collect, load_records
from .config import ConfigError, load_settings
from .source import SourceError, sanity_check
from .storage.clients import StorageClient, StorageUnavailable, open_storage
from .storage.migrations import MigrationError, MigrationRunner
from .storage.repository import AirportRepository
from .zh_names import ZhNamesError, load_llm_supplement, load_names, refresh_names


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airports-collector",
        description="从 OurAirports 采集机场数据到 InsForge 的 airports schema",
    )
    parser.add_argument("--repo-root", help="仓库根目录（默认当前目录）")
    parser.add_argument("--env-file", help="额外读取的 .env 文件")
    parser.add_argument("--quiet", action="store_true", help="只输出结果摘要")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="执行 migrations/ 下的 SQL 迁移")
    subparsers.add_parser("validate-schema", help="校验 airports schema 是否符合预期")
    subparsers.add_parser("status", help="输出 airports schema 的统计信息")

    export_parser = subparsers.add_parser(
        "export-web", help="生成展示端快照（airports.json.gz + manifest）"
    )
    export_parser.add_argument("--csv", help="使用本地 CSV 而不是下载源站")
    export_parser.add_argument("--names", help="中文名 CSV（默认 data/airport_names_zh.csv）")
    export_parser.add_argument("--out", help="输出目录（默认 web/globe/public）")
    export_parser.add_argument("--no-gzip", action="store_true", help="输出未压缩的 airports.json")

    collect_parser = subparsers.add_parser("collect", help="采集并入库（默认整份下载）")
    collect_parser.add_argument("--csv", help="使用本地 CSV 而不是下载源站")
    collect_parser.add_argument(
        "--allow-missing-names",
        action="store_true",
        help="中文名文件缺失或未解析时继续（默认报错）",
    )

    names_parser = subparsers.add_parser("names", help="中文名相关操作")
    names_sub = names_parser.add_subparsers(dest="names_command", required=True)
    refresh = names_sub.add_parser("refresh", help="从 Wikidata/维基百科重新生成中文名 CSV")
    refresh.add_argument("--csv", help="使用本地 CSV 而不是下载源站")
    refresh.add_argument("--out", help="输出路径（默认 data/airport_names_zh.csv）")
    refresh.add_argument(
        "--llm-fallback",
        action="store_true",
        help="对仍无中文名的机场调用本机 codex exec 兜底（慢，会消耗模型额度）",
    )
    refresh.add_argument("--llm-model", help="传给 codex exec -m 的模型名，例如 deepseek-v4.1-flash")
    refresh.add_argument("--llm-batch-size", type=int, default=100, help="每次 LLM 请求的机场条数")
    refresh.add_argument("--llm-timeout", type=int, default=600, help="单次 LLM 请求超时（秒）")
    refresh.add_argument(
        "--llm-supplement",
        help="LLM 中文名存档路径（默认 data/airport_names_llm.csv；不存在则不合并）",
    )
    refresh.add_argument(
        "--no-llm-supplement", action="store_true", help="忽略 LLM 存档，只用权威来源与合成"
    )
    extract = names_sub.add_parser("extract-llm", help="从主 CSV 里把 LLM 生成的名字拆成存档")
    extract.add_argument("--from", dest="source", help="主 CSV（默认 data/airport_names_zh.csv）")
    extract.add_argument("--out", help="存档输出（默认 data/airport_names_llm.csv）")
    return parser


def _progress_printer(quiet: bool):
    def printer(message: str) -> None:
        if not quiet:
            print(message, flush=True)

    return printer


def _open_storage(settings, progress) -> StorageClient:
    return open_storage(settings, on_progress=progress)


def run_command(args: argparse.Namespace) -> int:
    settings = load_settings(repo_root=args.repo_root, env_file=args.env_file)
    progress = _progress_printer(args.quiet)

    if args.command == "names" and args.names_command == "extract-llm":
        from .zh_names import write_llm_supplement

        source = Path(args.source) if args.source else settings.names_file
        target = Path(args.out) if args.out else settings.llm_supplement_file
        entries = load_names(source)
        saved = write_llm_supplement(target, entries.values())
        print(f"已从 {source} 提取 {saved} 条 LLM 名字到 {target}")
        return 0

    if args.command == "names":
        out_path = args.out or settings.names_file
        with httpx.Client() as http_client:
            records, _ = load_records(
                csv_path=args.csv,
                http_client=http_client,
                source_url=settings.source_url,
                on_progress=progress,
            )
            sanity_check(records)
            supplement_path = (
                Path(args.llm_supplement) if args.llm_supplement else settings.llm_supplement_file
            )
            supplement = (
                {} if args.no_llm_supplement else load_llm_supplement(supplement_path)
            )
            if supplement and not args.quiet:
                print(f"载入 LLM 存档 {supplement_path}（{len(supplement)} 条）")
            provider = None
            if args.llm_fallback:
                from .llm_fallback import CodexExecProvider

                provider = CodexExecProvider(model=args.llm_model, timeout=args.llm_timeout)
            stats = refresh_names(
                http_client,
                records,
                out_path,
                llm_supplement=supplement,
                llm_provider=provider,
                llm_batch_size=args.llm_batch_size,
                llm_supplement_out=None if args.no_llm_supplement else supplement_path,
                on_progress=progress,
            )
        print(stats.summary())
        print(f"输出文件: {out_path}")
        return 0

    storage = _open_storage(settings, progress)
    try:
        if args.command == "migrate":
            runner = MigrationRunner(storage, settings.migration_dir)
            applied = runner.migrate()
            if applied:
                print(f"已应用迁移: {', '.join(applied)}")
            else:
                print("没有待应用的迁移")
            problems = runner.validate()
            if problems:
                print("schema 校验失败:", file=sys.stderr)
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 1
            return 0

        if args.command == "validate-schema":
            problems = MigrationRunner(storage, settings.migration_dir).validate()
            if problems:
                print("schema 校验失败:", file=sys.stderr)
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 1
            print("airports schema 校验通过")
            return 0

        if args.command == "export-web":
            from .web_export import export_web

            names_path = Path(args.names) if args.names else settings.names_file
            out_dir = Path(args.out) if args.out else settings.web_export_dir
            with httpx.Client() as http_client:
                records, download = load_records(
                    csv_path=args.csv,
                    http_client=http_client,
                    source_url=settings.source_url,
                    on_progress=progress,
                )
            sanity_check(records)
            names = load_names(names_path)
            result = export_web(
                records,
                names,
                out_dir,
                source_url=settings.source_url,
                source_sha256=download.sha256 if download else "",
                    names_file=names_path.relative_to(settings.repo_root)
                if names_path.is_relative_to(settings.repo_root)
                else names_path,
                compress=not args.no_gzip,
            )
            print(result.summary())
            print(f"快照: {result.snapshot_path}")
            print(f"manifest: {result.manifest_path}")
            return 0

        if args.command == "status":
            stats = AirportRepository(storage).stats()
            if not stats:
                print("airports schema 还没有数据")
                return 0
            for key, value in stats.items():
                print(f"{key}: {value}")
            return 0

        if args.command == "collect":
            problems = MigrationRunner(storage, settings.migration_dir).validate()
            if problems:
                raise MigrationError(
                    "airports schema 未就绪，请先运行 airports-collector migrate："
                    + "; ".join(problems)
                )
            with httpx.Client() as http_client:
                result = collect(
                    AirportRepository(storage, batch_size=settings.batch_size),
                    http_client,
                    source_url=settings.source_url,
                    names_path=settings.names_file,
                    csv_path=args.csv,
                    allow_missing_names=args.allow_missing_names,
                    on_progress=progress,
                )
            print(result.summary())
            return 0
    finally:
        storage.close()

    raise AssertionError(f"未知命令: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return run_command(args)
    except (ConfigError, SourceError, ZhNamesError, MigrationError, StorageUnavailable) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
