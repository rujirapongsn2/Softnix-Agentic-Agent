from softnix_agentic_agent.agent.planner import _parse_plan_json


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
