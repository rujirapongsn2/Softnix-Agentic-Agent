from __future__ import annotations

FINAL_OUTPUT_MAX_CHARS = 4000


def help_text() -> str:
    return (
        "Natural mode: send plain text to run task directly (no /run needed)\n"
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
    short = (output or "").strip()
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
