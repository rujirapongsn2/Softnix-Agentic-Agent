from datetime import datetime, timezone

import pytest

from softnix_agentic_agent.integrations.schedule_parser import parse_natural_schedule_text


def test_parse_today_time_to_one_time() -> None:
    parsed = parse_natural_schedule_text(
        "วันนี้ 09:00 ช่วยสรุปข้อมูลจาก www.softnix.ai",
        timezone_name="Asia/Bangkok",
        now_utc=datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc),
    )
    assert parsed.schedule_type == "one_time"
    assert parsed.run_at == "2026-02-10T02:00:00+00:00"
    assert parsed.task == "ช่วยสรุปข้อมูลจาก www.softnix.ai"


def test_parse_daily_to_cron() -> None:
    parsed = parse_natural_schedule_text(
        "ทุกวัน 09:15 สรุปข่าว AI",
        timezone_name="Asia/Bangkok",
    )
    assert parsed.schedule_type == "cron"
    assert parsed.cron_expr == "15 9 * * *"
    assert parsed.task == "สรุปข่าว AI"


def test_parse_weekly_to_cron() -> None:
    parsed = parse_natural_schedule_text(
        "ทุกวันจันทร์ 08:30 สรุปข่าว AI รายสัปดาห์",
        timezone_name="Asia/Bangkok",
    )
    assert parsed.schedule_type == "cron"
    assert parsed.cron_expr == "30 8 * * 1"


def test_parse_unsupported_format_raises() -> None:
    with pytest.raises(ValueError):
        parse_natural_schedule_text("ช่วยสรุปทุกเช้า", timezone_name="Asia/Bangkok")

