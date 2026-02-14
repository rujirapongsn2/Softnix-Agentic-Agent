from __future__ import annotations

import re

FINAL_OUTPUT_MAX_CHARS = 4000


def help_text() -> str:
    return (
        "Natural mode: send plain text to run task directly (no /run needed)\n"
        "Upload mode: attach file (document/pdf) with caption to run task using that file\n"
        "Risky tasks require confirmation: reply yes/no or /yes /no\n\n"
        "Commands:\n"
        "/run <task>\n"
        "/yes | /no\n"
        "/schedule <today/tomorrow/daily text>\n"
        "/schedules\n"
        "/schedule_runs <schedule_id>\n"
        "/schedule_disable <schedule_id>\n"
        "/schedule_delete <schedule_id>\n"
        "/status <run_id>\n"
        "/cancel <run_id>\n"
        "/resume <run_id>\n"
        "/pending <run_id>\n"
        "/skill_build <task>\n"
        "/skill_status <job_id>\n"
        "/skill_builds\n"
        "/skill_delete <skill_name>\n"
        "/skills\n"
        "/context\n"
        "/help"
    )


def started_text(run_id: str, task: str) -> str:
    preview = task if len(task) <= 120 else f"{task[:117]}..."
    return f"Started run: {run_id}\nTask: {preview}\nUse /status {run_id}"


def status_text(run_id: str, status: str, iteration: int, max_iters: int, stop_reason: str) -> str:
    return (
        f"Run {run_id}: {status}\n"
        f"iteration: {iteration}/{max_iters}\n"
        f"stop_reason: {stop_reason or '-'}"
    )


def pending_text(run_id: str, items: list[dict]) -> str:
    if not items:
        return f"Run {run_id}: No pending memory"
    lines = [f"Run {run_id}: pending memory ({len(items)})"]
    for item in items[:20]:
        key = str(item.get("target_key", ""))
        value = str(item.get("value", ""))
        lines.append(f"- {key}={value}")
    return "\n".join(lines)


def final_run_text(run_id: str, status: str, iteration: int, max_iters: int, stop_reason: str, output: str) -> str:
    short = _markdown_to_plain_text((output or "").strip())
    if len(short) > FINAL_OUTPUT_MAX_CHARS:
        short = short[: FINAL_OUTPUT_MAX_CHARS - 3] + "..."
    lines = [
        f"Run {run_id}: {status}",
        f"iteration: {iteration}/{max_iters}",
        f"stop_reason: {stop_reason or '-'}",
    ]
    if short:
        lines.append("")
        lines.append(short)
    return "\n".join(lines)


def _markdown_to_plain_text(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    lines: list[str] = []
    for line in raw.splitlines():
        cur = line.rstrip()
        if not cur:
            lines.append("")
            continue
        # Drop markdown table separators.
        if re.fullmatch(r"\s*\|?[:\- ]+\|[:\-| ]*\s*", cur):
            continue
        # Remove heading markers and list bullets.
        cur = re.sub(r"^\s{0,3}#{1,6}\s*", "", cur)
        cur = re.sub(r"^\s*[-*+]\s+", "- ", cur)
        # Convert table row pipes to plain separators.
        if "|" in cur:
            cur = cur.strip().strip("|")
            cur = " | ".join(part.strip() for part in cur.split("|"))
        # Remove markdown emphasis/code markers.
        cur = re.sub(r"[*_`~]", "", cur)
        cur = re.sub(r"\s{2,}", " ", cur).strip()
        lines.append(cur)
    compact: list[str] = []
    prev_blank = False
    for line in lines:
        blank = line == ""
        if blank and prev_blank:
            continue
        compact.append(line)
        prev_blank = blank
    return "\n".join(compact).strip()
