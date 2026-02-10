from softnix_agentic_agent.integrations.telegram_parser import parse_telegram_command


def test_parse_telegram_command_basic() -> None:
    cmd = parse_telegram_command("/run สวัสดี")
    assert cmd is not None
    assert cmd.name == "run"
    assert cmd.arg == "สวัสดี"


def test_parse_telegram_command_with_bot_suffix() -> None:
    cmd = parse_telegram_command("/status@softnix_bot run123")
    assert cmd is not None
    assert cmd.name == "status"
    assert cmd.arg == "run123"


def test_parse_telegram_command_unknown_falls_back_to_help() -> None:
    cmd = parse_telegram_command("/unknown x")
    assert cmd is not None
    assert cmd.name == "help"


def test_parse_telegram_command_non_command_returns_none() -> None:
    assert parse_telegram_command("hello") is None


def test_parse_telegram_schedule_command() -> None:
    cmd = parse_telegram_command("/schedule ทุกวัน 09:00 สรุปข่าว AI")
    assert cmd is not None
    assert cmd.name == "schedule"
    assert cmd.arg == "ทุกวัน 09:00 สรุปข่าว AI"


def test_parse_telegram_schedules_command() -> None:
    cmd = parse_telegram_command("/schedules")
    assert cmd is not None
    assert cmd.name == "schedules"
    assert cmd.arg == ""


def test_parse_telegram_schedule_disable_command() -> None:
    cmd = parse_telegram_command("/schedule_disable abc123")
    assert cmd is not None
    assert cmd.name == "schedule_disable"
    assert cmd.arg == "abc123"
