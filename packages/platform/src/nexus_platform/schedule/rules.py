"""Schedule rules: every N minutes, daily at a time, weekly on a day and time, in an IANA time zone.

A rule is a small dict, validated here and nowhere else, so the model cannot smuggle in something the scheduler
does not understand. Cron expressions are deliberately not supported: the three shapes cover what people ask for
and cannot express "every second". The shortest interval is `MIN_INTERVAL_MINUTES`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 7 * 24 * 60
WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')


class ScheduleError(ValueError):
    """An invalid schedule. `code` is stable and safe to show."""

    def __init__(self, code: str, detail: str = ''):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Rule:
    kind: str
    every_minutes: int = 0
    hour: int = 0
    minute: int = 0
    weekday: int = 0

    def as_dict(self) -> dict:
        if self.kind == 'interval':
            return {'kind': 'interval', 'every_minutes': self.every_minutes}
        at = f'{self.hour:02d}:{self.minute:02d}'
        return {'kind': 'daily', 'at': at} if self.kind == 'daily' else {'kind': 'weekly', 'weekday': self.weekday, 'at': at}

    def describe(self) -> str:
        if self.kind == 'interval':
            return f'every {self.every_minutes} minutes'
        at = f'{self.hour:02d}:{self.minute:02d}'
        return f'every day at {at}' if self.kind == 'daily' else f'every {WEEKDAYS[self.weekday]} at {at}'


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ScheduleError('schedule_timezone_invalid', 'use an IANA name such as Asia/Shanghai') from None


def _time(value) -> tuple[int, int]:
    try:
        hour, minute = (int(part) for part in str(value).split(':'))
    except (ValueError, TypeError):
        raise ScheduleError('schedule_invalid', 'time must look like 09:30') from None
    if not (0 <= hour < 24 and 0 <= minute < 60) or len(str(value)) != 5:
        raise ScheduleError('schedule_invalid', 'time must look like 09:30')
    return hour, minute


def parse(data) -> Rule:
    """Validate a rule dict. Raises ScheduleError."""
    if not isinstance(data, dict):
        raise ScheduleError('schedule_invalid', 'the schedule must be an object')
    kind = data.get('kind')
    if kind == 'interval':
        minutes = data.get('every_minutes')
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            raise ScheduleError('schedule_interval_invalid', f'every_minutes must be {MIN_INTERVAL_MINUTES}-{MAX_INTERVAL_MINUTES}')
        return Rule('interval', every_minutes=minutes)
    if kind == 'daily':
        hour, minute = _time(data.get('at'))
        return Rule('daily', hour=hour, minute=minute)
    if kind == 'weekly':
        day = data.get('weekday')
        if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
            raise ScheduleError('schedule_invalid', 'weekday is 0 (Monday) to 6 (Sunday)')
        hour, minute = _time(data.get('at'))
        return Rule('weekly', hour=hour, minute=minute, weekday=day)
    raise ScheduleError('schedule_invalid', 'kind must be interval, daily or weekly')


def next_after(rule: Rule, tz: ZoneInfo, after: datetime) -> datetime:
    """The first fire time strictly after `after`, as an aware UTC datetime."""
    after = after.astimezone(timezone.utc) if after.tzinfo else after.replace(tzinfo=timezone.utc)
    if rule.kind == 'interval':
        return after + timedelta(minutes=rule.every_minutes)
    local = after.astimezone(tz)
    for offset in range(15):
        day = local.date() + timedelta(days=offset)
        candidate = datetime(day.year, day.month, day.day, rule.hour, rule.minute, tzinfo=tz)
        if rule.kind == 'weekly' and candidate.weekday() != rule.weekday:
            continue
        if candidate.astimezone(timezone.utc) > after:
            return candidate.astimezone(timezone.utc)
    raise ScheduleError('schedule_invalid', 'no next time found')  # unreachable for valid rules
