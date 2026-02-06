from __future__ import annotations

import json
from typing import Any

from softnix_agentic_agent.providers.base import LLMProvider


SYSTEM_PROMPT = """
You are Softnix Agent Planner.
Return STRICT JSON only with shape:
{
  "thought": "short reasoning",
  "done": boolean,
  "final_output": "string when done=true else optional",
  "actions": [
    {"name": "list_dir|read_file|write_workspace_file|run_safe_command", "params": {...}}
  ]
}
Rules:
- Do not include markdown.
- Prefer small safe actions.
- Use done=true only when task is complete.
""".strip()


class Planner:
    def __init__(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model

    def build_plan(
        self,
        task: str,
        iteration: int,
        max_iters: int,
        previous_output: str,
        skills_context: str,
    ) -> tuple[dict[str, Any], dict[str, int], str]:
        user_prompt = (
            f"Task: {task}\n"
            f"Iteration: {iteration}/{max_iters}\n"
            f"Previous output: {previous_output or 'N/A'}\n"
            f"Skills:\n{skills_context}\n"
            "Return JSON plan now."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        resp = self.provider.generate(messages=messages, model=self.model)
        parsed = _parse_plan_json(resp.content)
        return parsed, resp.usage, user_prompt


def _parse_plan_json(content: str) -> dict[str, Any]:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass

    return {
        "thought": "fallback parse: invalid JSON from model",
        "done": True,
        "final_output": content,
        "actions": [],
    }
