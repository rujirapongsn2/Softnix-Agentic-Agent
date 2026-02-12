from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TelegramCommand:
    name: str
    arg: str


SUPPORTED_COMMANDS = {
    "run",
    "yes",
    "no",
    "confirm",
    "reject",
    "schedule",
    "schedules",
    "schedule_runs",
    "schedule_disable",
    "schedule_delete",
    "status",
    "cancel",
    "resume",
    "pending",
    "skill_build",
    "skill_status",
    "skill_builds",
    "help",
}


def parse_telegram_command(text: str) -> TelegramCommand | None:
    raw = (text or "").strip()
    if not raw or not raw.startswith("/"):
        return None
    parts = raw.split(maxsplit=1)
    head = parts[0][1:]
    if "@" in head:
        head = head.split("@", 1)[0]
    name = head.strip().lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if name not in SUPPORTED_COMMANDS:
        return TelegramCommand(name="help", arg="")
    return TelegramCommand(name=name, arg=arg)
