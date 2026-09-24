"""把公开源 CSV + 中文名 CSV 合成展示端快照。

快照形状（schemaVersion = 1）：

    {
      "schemaVersion": 1,
      "generatedAt": "2026-09-24T02:00:00+00:00",
      "source": {"url": ..., "sha256": ..., "rowCount": ...},
      "names":  {"file": ..., "sha256": ..., "rowCount": ...},
      "fields": ["id", "ident", ...],
      "rows": [[...], ...]
    }

行是有序数组（比对象省约 30% 体积、解析更快），`fields` 自带字段表所以仍然自描述。
只导出当前源快照的真实状态：源里没有的行就是已经不存在，因此不导出 `is_active`。
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .source import AirportRecord
from .zh_names import TARGET_TYPES, NameEntry

SCHEMA_VERSION = 1

SNAPSHOT_FIELDS: tuple[str, ...] = (
    "id",
    "ident",
    "type",
    "name",
    "latitude_deg",
    "longitude_deg",
    "elevation_ft",
    "continent",
    "iso_country",
    "iso_region",
    "municipality",
    "scheduled_service",
    "gps_code",
    "icao_code",
    "iata_code",
    "local_code",
    "home_link",
    "wikipedia_link",
    "keywords",
    "name_zh",
    "name_zh_source",
    "municipality_zh",
    "municipality_zh_source",
    "location_zh",
    "location_zh_source",
)


@dataclass
class ExportResult:
    snapshot_path: Path
    manifest_path: Path
    rows: int
    snapshot_bytes: int
    compressed_bytes: int
    snapshot_sha256: str
    type_counts: dict[str, int] = field(default_factory=dict)
    named_rows: int = 0
    unresolved_targets: int = 0

    def summary(self) -> str:
        ratio = 100.0 * self.compressed_bytes / self.snapshot_bytes if self.snapshot_bytes else 0.0
        return (
            f"快照 {self.rows} 行：{self.snapshot_bytes / 1048576:.1f} MB → "
            f"gzip {self.compressed_bytes / 1048576:.2f} MB（{ratio:.0f}%）；"
            f"有中文名 {self.named_rows} 行，目标机场未解析 {self.unresolved_targets} 行"
        )


def _row(record: AirportRecord, entry: NameEntry | None) -> list[Any]:
    values: dict[str, Any] = {
        "id": record.id,
        "ident": record.ident,
        "type": record.type,
        "name": record.name,
        "latitude_deg": record.latitude_deg,
        "longitude_deg": record.longitude_deg,
        "elevation_ft": record.elevation_ft,
        "continent": record.continent,
        "iso_country": record.iso_country,
        "iso_region": record.iso_region,
        "municipality": record.municipality,
        "scheduled_service": record.scheduled_service,
        "gps_code": record.gps_code,
        "icao_code": record.icao_code,
        "iata_code": record.iata_code,
        "local_code": record.local_code,
        "home_link": record.home_link,
        "wikipedia_link": record.wikipedia_link,
        "keywords": record.keywords,
        "name_zh": entry.name_zh if entry else None,
        "name_zh_source": entry.name_zh_source if entry else None,
        "municipality_zh": entry.municipality_zh if entry else None,
        "municipality_zh_source": entry.municipality_zh_source if entry else None,
        "location_zh": entry.location_zh if entry else None,
        "location_zh_source": entry.location_zh_source if entry else None,
    }
    return [values[name] for name in SNAPSHOT_FIELDS]


def build_snapshot(
    records: Sequence[AirportRecord],
    names: dict[int, NameEntry],
    *,
    source_url: str,
    source_sha256: str,
    names_file: str,
    names_sha256: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    ordered = sorted(records, key=lambda record: record.id)
    rows = [_row(record, names.get(record.id)) for record in ordered]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "source": {"url": source_url, "sha256": source_sha256, "rowCount": len(records)},
        "names": {"file": names_file, "sha256": names_sha256, "rowCount": len(names)},
        "fields": list(SNAPSHOT_FIELDS),
        "rows": rows,
    }


def summarize(records: Iterable[AirportRecord], names: dict[int, NameEntry]) -> dict[str, Any]:
    type_counts: dict[str, int] = {}
    named_rows = 0
    unresolved_targets = 0
    for record in records:
        type_counts[record.type] = type_counts.get(record.type, 0) + 1
        entry = names.get(record.id)
        if entry and entry.name_zh:
            named_rows += 1
        if record.type in TARGET_TYPES and not (entry and entry.name_zh):
            unresolved_targets += 1
    return {
        "typeCounts": dict(sorted(type_counts.items())),
        "namedRows": named_rows,
        "unresolvedTargets": unresolved_targets,
    }


def write_export(
    snapshot: dict[str, Any],
    out_dir: Path,
    *,
    compress: bool = True,
) -> tuple[Path, Path, int, int, str]:
    """写出快照与 manifest，返回 (快照路径, manifest 路径, 原始字节, 存储字节, sha256)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    if compress:
        snapshot_path = out_dir / "airports.json.gz"
        snapshot_path.write_bytes(gzip.compress(payload, 9))
    else:
        snapshot_path = out_dir / "airports.json"
        snapshot_path.write_bytes(payload)
    return snapshot_path, out_dir / "manifest.json", len(payload), snapshot_path.stat().st_size, digest


def export_web(
    records: Sequence[AirportRecord],
    names: dict[int, NameEntry],
    out_dir: Path,
    *,
    source_url: str,
    source_sha256: str,
    names_file: Path,
    compress: bool = True,
) -> ExportResult:
    names_sha256 = hashlib.sha256(names_file.read_bytes()).hexdigest() if names_file.exists() else ""
    snapshot = build_snapshot(
        records,
        names,
        source_url=source_url,
        source_sha256=source_sha256,
        names_file=str(names_file),
        names_sha256=names_sha256,
    )
    stats = summarize(records, names)
    snapshot_path, manifest_path, raw_bytes, stored_bytes, digest = write_export(
        snapshot, out_dir, compress=compress
    )
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": snapshot["generatedAt"],
        "rows": len(records),
        "snapshot": {
            "path": snapshot_path.name,
            "uncompressedBytes": raw_bytes,
            "storedBytes": stored_bytes,
            "sha256": digest,
            "compressed": compress,
        },
        "source": snapshot["source"],
        "names": snapshot["names"],
        **stats,
        "fields": list(SNAPSHOT_FIELDS),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return ExportResult(
        snapshot_path=snapshot_path,
        manifest_path=manifest_path,
        rows=len(records),
        snapshot_bytes=raw_bytes,
        compressed_bytes=stored_bytes,
        snapshot_sha256=digest,
        type_counts=stats["typeCounts"],
        named_rows=stats["namedRows"],
        unresolved_targets=stats["unresolvedTargets"],
    )
