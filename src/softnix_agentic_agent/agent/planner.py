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
    {"name": "list_dir|read_file|write_workspace_file|write_file|run_safe_command|run_shell_command|run_python_code|web_fetch", "params": {...}}
  ]
}
Rules:
- Do not include markdown.
- Prefer small safe actions.
- Prefer iterative loop: write code -> run code -> inspect result -> refine.
- Use done=true only when task is complete.
- For file transformation tasks, done=true is allowed only after output file is actually created and verified.
- If you create a script, you must execute it (run_python_code or run_shell_command) in a later action.
- After execution, verify expected output with list_dir/read_file before done=true.
- For file actions, always use params.path (not file_path).
- Use paths relative to workspace (e.g. "index.html", "assets/app.js"), never absolute paths.
- For web fetch, use params.url with full http/https URL.
- For run_python_code:
  - use params.code as full Python script
  - optional params.path for script path under workspace
  - optional params.args as string array
- For run_shell_command / run_safe_command:
  - command base must be allowlisted
  - never use destructive or privileged commands
  - if using rm, always include at least one target path in the same command
  - for deletion tasks, verify removal using list_dir/read_file before done=true
- Avoid ending with code text only; prefer actionable steps that produce verifiable files/results.
- Keep responses compact and valid JSON. Never wrap with ``` fences.
- If content is long, split work into multiple iterations and use mode="append".
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
        memory_context: str = "",
    ) -> tuple[dict[str, Any], dict[str, int], str]:
        user_prompt = (
            f"Task: {task}\n"
            f"Iteration: {iteration}/{max_iters}\n"
            f"Previous output: {previous_output or 'N/A'}\n"
            f"Memory:\n{memory_context or '- none'}\n"
            f"Skills:\n{skills_context}\n"
            "Return JSON plan now."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        resp = self.provider.generate(messages=messages, model=self.model, max_tokens=4096)
        parsed = _parse_plan_json(resp.content)
        return parsed, resp.usage, user_prompt


def _parse_plan_json(content: str) -> dict[str, Any]:
    content = _strip_code_fence(content.strip())
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
        "done": False,
        "final_output": "planner_parse_error: model returned invalid or truncated JSON",
        "actions": [],
    }


def _strip_code_fence(content: str) -> str:
    if content.startswith("```"):
        lines = content.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return content
