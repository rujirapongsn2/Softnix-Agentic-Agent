from __future__ import annotations

import json
from typing import Any

from softnix_agentic_agent.providers.base import LLMProvider

MAX_PREVIOUS_OUTPUT_CHARS = 4000


SYSTEM_PROMPT = """
You are Softnix Agent Planner.
Return STRICT JSON only with shape:
{
  "thought": "short reasoning",
  "done": boolean,
  "final_output": "string when done=true else optional",
  "validations": [
    {"type": "file_exists|text_in_file", "path": "relative/path", "contains": "optional for text_in_file"}
  ],
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
- For done=true, provide `validations` whenever objective checks are known (especially output files).
- If skill context provides `scripts/...`, prefer running that script instead of rewriting equivalent ad-hoc code.
- For file actions, always use params.path (not file_path).
- Use paths relative to workspace (e.g. "index.html", "assets/app.js"), never absolute paths.
- For web fetch, use params.url with full http/https URL.
- For tasks that ask to summarize/analyze a website or include an http/https URL:
  - Prefer `web_fetch` first, then summarize from fetched content.
  - Avoid `run_python_code` unless the user explicitly asks to write/execute Python.
  - Do not rely on external Python packages (e.g. requests/bs4) for basic webpage summarization.
- For run_python_code:
  - use params.code as full Python script
  - optional params.path for script path under workspace
  - optional params.args as string array
  - if setting python_bin, use "python" (never "python3")
  - when executing a skill script from skills context, call `run_python_code` with params.path directly (no subprocess wrapper inside params.code)
  - for skill script paths, use skill-relative form like `web-intel/scripts/web_intel_fetch.py` (do not prefix with `skillpacks/`)
  - if output contains `fallback_required=true` from web-intel script, treat as degraded success and continue by reading `web_intel/summary.md` and `web_intel/meta.json` (do not retry the same command unchanged)
- For run_shell_command / run_safe_command:
  - command base must be allowlisted
  - optional params.args as string array for command arguments
  - to save command output to file, use params.stdout_path / params.stderr_path
  - do not rely on shell redirection operators like `>` or `2>&1`
  - when running Python in shell command, use `python` (not `python3`)
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
        compact_previous_output = _compact_previous_output(previous_output, max_chars=MAX_PREVIOUS_OUTPUT_CHARS)
        user_prompt = (
            f"Task: {task}\n"
            f"Iteration: {iteration}/{max_iters}\n"
            f"Previous output: {compact_previous_output or 'N/A'}\n"
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


def _compact_previous_output(text: str, max_chars: int = MAX_PREVIOUS_OUTPUT_CHARS) -> str:
    raw = (text or "").strip()
    if len(raw) <= max_chars:
        return raw
    keep_head = max(200, int(max_chars * 0.8))
    keep_tail = max(120, max_chars - keep_head)
    head = raw[:keep_head].rstrip()
    tail = raw[-keep_tail:].lstrip()
    return (
        f"{head}\n\n[truncated previous output: showing first {keep_head} and last {keep_tail} chars]\n\n{tail}"
    )
