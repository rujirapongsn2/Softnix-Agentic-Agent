from types import SimpleNamespace

from softnix_agentic_agent.agent.planner import MAX_PREVIOUS_OUTPUT_CHARS, Planner, _compact_previous_output, _parse_plan_json


def test_parse_fenced_json() -> None:
    raw = """```json
{"thought":"ok","done":false,"actions":[{"name":"list_dir","params":{"path":"."}}]}
```"""
    plan = _parse_plan_json(raw)
    assert plan["done"] is False
    assert plan["actions"][0]["name"] == "list_dir"


def test_parse_invalid_json_fallback_not_done() -> None:
    raw = """```json
{"thought":"x","done":false,"actions":[{"name":"write_workspace_file"
"""
    plan = _parse_plan_json(raw)
    assert plan["done"] is False
    assert plan["actions"] == []
    assert "planner_parse_error" in plan["final_output"]


def test_compact_previous_output_truncates_long_text() -> None:
    source = ("A" * (MAX_PREVIOUS_OUTPUT_CHARS + 2000)).strip()
    compact = _compact_previous_output(source)
    assert len(compact) < len(source)
    assert "truncated previous output" in compact


def test_planner_build_plan_uses_compacted_previous_output() -> None:
    class _FakeProvider:
        def __init__(self) -> None:
            self.last_messages = []

        def generate(self, messages, model, max_tokens):  # type: ignore[no-untyped-def]
            self.last_messages = messages
            return SimpleNamespace(
                content='{"thought":"ok","done":false,"actions":[]}',
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            )

    provider = _FakeProvider()
    planner = Planner(provider=provider, model="m")
    previous_output = "X" * (MAX_PREVIOUS_OUTPUT_CHARS + 5000)
    plan, usage, prompt = planner.build_plan(
        task="demo",
        iteration=1,
        max_iters=10,
        previous_output=previous_output,
        skills_context="- none",
        memory_context="- none",
    )

    assert plan["done"] is False
    assert usage["total_tokens"] == 2
    assert "truncated previous output" in prompt
    assert len(prompt) < len(previous_output)


def test_planner_build_plan_adds_final_iteration_guard() -> None:
    class _FakeProvider:
        def __init__(self) -> None:
            self.last_messages = []

        def generate(self, messages, model, max_tokens):  # type: ignore[no-untyped-def]
            self.last_messages = messages
            return SimpleNamespace(
                content='{"thought":"ok","done":false,"actions":[]}',
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            )

    provider = _FakeProvider()
    planner = Planner(provider=provider, model="m")
    plan, usage, prompt = planner.build_plan(
        task="สรุปข้อมูลเว็บไซต์",
        iteration=10,
        max_iters=10,
        previous_output="ok",
        skills_context="- none",
        memory_context="- none",
    )
    assert plan["done"] is False
    assert usage["total_tokens"] == 2
    assert "Final-iteration guard:" in prompt
