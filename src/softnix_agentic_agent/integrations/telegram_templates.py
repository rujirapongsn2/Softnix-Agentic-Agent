from __future__ import annotations


def help_text() -> str:
    return (
        "Commands:\n"
        "/run <task>\n"
        "/status <run_id>\n"
        "/cancel <run_id>\n"
        "/resume <run_id>\n"
        "/pending <run_id>\n"
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
    if len(short) > 400:
        short = short[:397] + "..."
    lines = [
        f"Run {run_id}: {status}",
        f"iteration: {iteration}/{max_iters}",
        f"stop_reason: {stop_reason or '-'}",
    ]
    if short:
        lines.append("")
        lines.append(short)
    return "\n".join(lines)
