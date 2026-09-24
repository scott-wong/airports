from __future__ import annotations

import pytest

from airports_collector.llm_fallback import (
    LlmFallbackError,
    NameRequest,
    build_prompt,
    parse_name_map,
    suggest_names,
    validate_name,
)
from airports_collector.zh_names import compose_name


def test_build_prompt_contains_items() -> None:
    prompt = build_prompt([NameRequest(1, "Kerema Airport", "PG", "Kerema")])
    assert '"id": 1' in prompt
    assert "Kerema Airport" in prompt
    assert "只输出一个 JSON 对象" in prompt


def test_parse_name_map_takes_last_json_object() -> None:
    output = '思考中……\n{"1": "甲机场"}\n最终：\n{"1": "凯里马机场", "2": null}\n'
    assert parse_name_map(output, [1, 2]) == {1: "凯里马机场", 2: None}


def test_parse_name_map_ignores_unrelated_ids() -> None:
    assert parse_name_map('{"9": "别的东西"}', [1, 2]) == {}


def test_parse_name_map_handles_fenced_json() -> None:
    output = '```json\n{"1": "凯里马机场"}\n```'
    assert parse_name_map(output, [1]) == {1: "凯里马机场"}


def test_validate_name() -> None:
    assert validate_name("凯里马机场", "Kerema Airport") == "凯里马机场"
    assert validate_name(None, "X Airport") is None
    assert validate_name("Kerema Airport", "Kerema Airport") is None
    assert validate_name("A", "X") is None
    assert validate_name("凯里马机场" * 10, "X") is None


class FakeProvider:
    label = "fake:test"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return self.replies.pop(0)


def test_suggest_names_batches_and_validates() -> None:
    provider = FakeProvider(['{"1": "凯里马机场", "2": null, "3": "Kerema Airport"}'])
    requests = [
        NameRequest(1, "Kerema Airport"),
        NameRequest(2, "Unknown Airport"),
        NameRequest(3, "Kerema Airport"),
    ]
    result = suggest_names(provider, requests, batch_size=10)
    assert result == {1: "凯里马机场"}
    assert provider.calls == 1


def test_suggest_names_splits_failed_batch() -> None:
    provider = FakeProvider(["not json at all", '{"1": "甲机场"}', '{"2": "乙机场"}'])
    requests = [NameRequest(1, "A Airport"), NameRequest(2, "B Airport")]
    result = suggest_names(provider, requests, batch_size=5)
    assert result == {1: "甲机场", 2: "乙机场"}
    assert provider.calls == 3


def test_suggest_names_gives_up_on_single() -> None:
    provider = FakeProvider(["still not json"])
    assert suggest_names(provider, [NameRequest(1, "A Airport")], batch_size=5) == {}


class RaisingProvider:
    label = "fake:raising"

    def complete(self, prompt: str) -> str:
        raise LlmFallbackError("boom")


def test_suggest_names_survives_provider_error() -> None:
    assert suggest_names(RaisingProvider(), [NameRequest(1, "A Airport")], batch_size=5) == {}


def test_compose_name_rules() -> None:
    assert compose_name("Kerema Airport", "Kerema", "凯里马") == "凯里马机场"
    assert compose_name("Linhares Municipal Airport", "Linhares", "利尼亚雷斯") == "利尼亚雷斯机场"
    assert compose_name("Kyurdamir Air Base", "Kyurdamir", "丘尔达米尔") == "丘尔达米尔空军基地"
    assert compose_name("Aracati Dragão do Mar Regional Airport", "Aracati", "阿拉卡蒂") is None
    assert compose_name("Kerema Airport", None, "凯里马") is None
    assert compose_name("Kerema Airport", "Kerema", None) is None


def test_codex_provider_command_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from airports_collector import llm_fallback

    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = '{"1": "甲机场"}'
        stderr = ""

    def fake_run(command, **kwargs):  # noqa: ANN001
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        return Completed()

    monkeypatch.setattr(llm_fallback.subprocess, "run", fake_run)
    provider = llm_fallback.CodexExecProvider(model="test-model")
    output = provider.complete("hello")
    assert output == '{"1": "甲机场"}'
    assert captured["input"] == "hello"
    command = captured["command"]
    assert command[0] == "codex" and "exec" in command
    assert "-m" in command and "test-model" in command
    assert 'web_search="disabled"' in command
    assert "mcp_servers={}" in command
    assert provider.label == "codex:test-model"
