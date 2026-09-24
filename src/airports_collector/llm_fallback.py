"""LLM 兜底：对 Wikidata / 维基百科都查不到的机场，用大模型给一个中文名。

设计约束：
- 只是“兜底”，永远排在前两个来源之后；
- 结果必须落在 name_zh_source 里（`llm:<model>`），消费方可以据此筛掉；
- 模型可以返回 null；本地再做一遍校验（必须含中文、不能是英文原名、不能超长等）；
- 默认用本机 `codex exec` 作为执行器，可用 --llm-model 指定模型。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .zh_names import CJK_RE, LATIN_WORD_RE

DEFAULT_BATCH_SIZE = 100
DEFAULT_TIMEOUT_SECONDS = 600
MAX_NAME_LENGTH = 40

PROMPT_HEADER = (
    "你是机场名称本地化助手。下面是机场的英文名、国家 ISO2、所在城市英文名。",
    "请给出该机场最常见的中文（简体）名称。规则：",
    "1. 只输出一个 JSON 对象，不要解释、不要 markdown 代码块；键是 id，值是中文名或 null；",
    "2. 用中国大陆常见译名（例：Los Angeles International Airport → 洛杉矶国际机场）；",
    "3. Airport/Airfield → 机场，Air Base/Air Force Base → 空军基地，Heliport → 直升机场；",
    "4. 不确定就输出 null，绝不编造。直接开始输出 JSON，不要做任何计划或搜索。",
    "",
    "数据：",
)


class LlmFallbackError(RuntimeError):
    """LLM 兜底失败。"""


@dataclass(frozen=True)
class NameRequest:
    id: int
    name: str
    country: str | None = None
    municipality: str | None = None
    type: str | None = None

    def to_json_line(self) -> str:
        payload = {
            "id": self.id,
            "name": self.name,
            "country": self.country or "",
            "city": self.municipality or "",
        }
        return json.dumps(payload, ensure_ascii=False)


def build_prompt(requests: Sequence[NameRequest]) -> str:
    lines = [*PROMPT_HEADER, "[", ",\n ".join(item.to_json_line() for item in requests), "]"]
    return "\n".join(lines)


def _iter_json_objects(text: str) -> list[dict[str, Any]]:
    """从模型输出里挑出所有可解析的 JSON 对象（忽略解释文字与代码块围栏）。"""
    objects: list[dict[str, Any]] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    chunk = text[start : index + 1]
                    try:
                        parsed = json.loads(chunk)
                    except ValueError:
                        continue
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                    start = None
    return objects


def parse_name_map(output: str, expected_ids: Sequence[int]) -> dict[int, str | None]:
    """取最后一个含合法 id 的 JSON 对象作为答案。"""
    expected = {int(item) for item in expected_ids}
    for candidate in reversed(_iter_json_objects(output)):
        hits: dict[int, str | None] = {}
        for key, value in candidate.items():
            try:
                key_id = int(str(key))
            except ValueError:
                continue
            if key_id not in expected:
                continue
            if value is None:
                hits[key_id] = None
            elif isinstance(value, str):
                hits[key_id] = value.strip()
        if hits:
            return hits
    return {}


def validate_name(name: str | None, english_name: str) -> str | None:
    if not name:
        return None
    text = name.strip().strip('"').strip()
    if not text or len(text) > MAX_NAME_LENGTH:
        return None
    if not CJK_RE.search(text) or LATIN_WORD_RE.search(text):
        return None
    if text.lower() == english_name.strip().lower():
        return None
    return text


class CodexExecProvider:
    """调用本机 `codex exec`，提示词走 stdin，只读 stdout。"""

    def __init__(
        self,
        model: str | None = None,
        *,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        executable: str = "codex",
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.executable = executable

    @property
    def label(self) -> str:
        return f"codex:{self.model}" if self.model else "codex:default"

    def complete(self, prompt: str) -> str:
        command = [
            self.executable,
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "-c",
            'web_search="disabled"',
            "-c",
            "mcp_servers={}",
        ]
        if self.model:
            command += ["-m", self.model]
        command.append("-")
        with tempfile.TemporaryDirectory(prefix="airports-llm-") as workdir:
            try:
                completed = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=workdir,
                )
            except FileNotFoundError as error:
                raise LlmFallbackError(
                    f"找不到可执行文件 {self.executable}；请安装 Codex CLI 或换用其它 provider"
                ) from error
            except subprocess.TimeoutExpired as error:
                raise LlmFallbackError(f"LLM 调用超时（{self.timeout}s）") from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "")[-500:]
            raise LlmFallbackError(f"codex exec 退出码 {completed.returncode}: {detail}")
        return completed.stdout


def suggest_names(
    provider: Any,
    requests: Sequence[NameRequest],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_progress: Callable[[str], None] | None = None,
) -> dict[int, str]:
    """批量获取建议名；解析失败的批次二分重试，最终失败的条目直接跳过。"""
    accepted: dict[int, str] = {}

    def progress(message: str) -> None:
        if on_progress:
            on_progress(message)

    def run(batch: list[NameRequest]) -> None:
        if not batch:
            return
        if len(batch) > batch_size:
            for start in range(0, len(batch), batch_size):
                run(batch[start : start + batch_size])
            return
        progress(f"  调用 LLM 处理 {len(batch)} 条（已接受 {len(accepted)}）")
        try:
            output = provider.complete(build_prompt(batch))
            raw = parse_name_map(output, [item.id for item in batch])
        except (LlmFallbackError, ValueError) as error:
            raw = {}
            progress(f"  批次失败：{error}")
        if not raw:
            if len(batch) == 1:
                progress(f"  放弃 {batch[0].id} {batch[0].name}")
                return
            middle = len(batch) // 2
            run(batch[:middle])
            run(batch[middle:])
            return
        for item in batch:
            value = validate_name(raw.get(item.id), item.name)
            if value:
                accepted[item.id] = value

    run(list(requests))
    return accepted
