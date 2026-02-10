from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo


_TIME_RE = r"(?P<hour>\d{1,2})[:.](?P<minute>\d{2})"
_THAI_WEEKDAY_TO_CRON = {
    "อาทิตย์": 0,
    "จันทร์": 1,
    "อังคาร": 2,
    "พุธ": 3,
    "พฤหัสบดี": 4,
    "ศุกร์": 5,
    "เสาร์": 6,
}


@dataclass
class ParsedScheduleText:
    schedule_type: str
    timezone: str
    task: str
    run_at: str | None = None
    cron_expr: str | None = None
    source_pattern: str = ""

    def to_dict(self) -> dict:
        return {
            "schedule_type": self.schedule_type,
            "timezone": self.timezone,
            "task": self.task,
            "run_at": self.run_at,
            "cron_expr": self.cron_expr,
            "source_pattern": self.source_pattern,
        }


def _parse_time(hour_text: str, minute_text: str) -> tuple[int, int]:
    hour = int(hour_text)
    minute = int(minute_text)
    if hour < 0 or hour > 23:
        raise ValueError("hour out of range")
    if minute < 0 or minute > 59:
        raise ValueError("minute out of range")
    return hour, minute


def _ensure_future_one_time(local_dt: datetime, now_local: datetime) -> datetime:
    if local_dt <= now_local:
        return local_dt + timedelta(days=1)
    return local_dt


def parse_natural_schedule_text(
    text: str,
    timezone_name: str,
    now_utc: datetime | None = None,
) -> ParsedScheduleText:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty schedule text")
    tz = ZoneInfo(timezone_name)
    now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)

    m_today = re.match(rf"^วันนี้\s+{_TIME_RE}\s+(.+)$", raw)
    if m_today:
        hour, minute = _parse_time(m_today.group("hour"), m_today.group("minute"))
        task = m_today.group(3).strip()
        local_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        local_dt = _ensure_future_one_time(local_dt, now)
        return ParsedScheduleText(
            schedule_type="one_time",
            timezone=timezone_name,
            task=task,
            run_at=local_dt.astimezone(timezone.utc).isoformat(),
            source_pattern="thai_today_time",
        )

    m_tomorrow = re.match(rf"^พรุ่งนี้\s+{_TIME_RE}\s+(.+)$", raw)
    if m_tomorrow:
        hour, minute = _parse_time(m_tomorrow.group("hour"), m_tomorrow.group("minute"))
        task = m_tomorrow.group(3).strip()
        local_dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return ParsedScheduleText(
            schedule_type="one_time",
            timezone=timezone_name,
            task=task,
            run_at=local_dt.astimezone(timezone.utc).isoformat(),
            source_pattern="thai_tomorrow_time",
        )

    m_daily = re.match(rf"^ทุกวัน\s+{_TIME_RE}\s+(.+)$", raw)
    if m_daily:
        hour, minute = _parse_time(m_daily.group("hour"), m_daily.group("minute"))
        task = m_daily.group(3).strip()
        return ParsedScheduleText(
            schedule_type="cron",
            timezone=timezone_name,
            task=task,
            cron_expr=f"{minute} {hour} * * *",
            source_pattern="thai_daily_time",
        )

    m_weekly = re.match(rf"^ทุกวัน(จันทร์|อังคาร|พุธ|พฤหัสบดี|ศุกร์|เสาร์|อาทิตย์)\s+{_TIME_RE}\s+(.+)$", raw)
    if m_weekly:
        weekday_text = m_weekly.group(1)
        hour, minute = _parse_time(m_weekly.group("hour"), m_weekly.group("minute"))
        task = m_weekly.group(4).strip()
        cron_dow = _THAI_WEEKDAY_TO_CRON[weekday_text]
        return ParsedScheduleText(
            schedule_type="cron",
            timezone=timezone_name,
            task=task,
            cron_expr=f"{minute} {hour} * * {cron_dow}",
            source_pattern="thai_weekday_time",
        )

    raise ValueError(
        "unsupported schedule text format; examples: "
        "'วันนี้ 09:00 ...', 'พรุ่งนี้ 09:00 ...', 'ทุกวัน 09:00 ...', 'ทุกวันจันทร์ 09:00 ...'"
    )
