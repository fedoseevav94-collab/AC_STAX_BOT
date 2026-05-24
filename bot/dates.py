from __future__ import annotations

from datetime import datetime, time, timedelta
from dataclasses import dataclass
import re


MONTHS = {
    "января": 1,
    "январь": 1,
    "февраля": 2,
    "февраль": 2,
    "марта": 3,
    "март": 3,
    "апреля": 4,
    "апрель": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июля": 7,
    "июль": 7,
    "августа": 8,
    "август": 8,
    "сентября": 9,
    "сентябрь": 9,
    "октября": 10,
    "октябрь": 10,
    "ноября": 11,
    "ноябрь": 11,
    "декабря": 12,
    "декабрь": 12,
}


@dataclass(frozen=True)
class ReturnPlan:
    text: str
    planned_at: datetime
    days: int


def parse_return_plan(text: str, now: datetime | None = None) -> ReturnPlan | None:
    now = now or datetime.now()
    raw_text = " ".join((text or "").strip().lower().split())
    if not raw_text:
        return None

    parsed_time = _parse_time(raw_text)
    return_time = parsed_time or time(23, 59)

    if "послезавтра" in raw_text:
        planned = datetime.combine((now + timedelta(days=2)).date(), return_time)
        return ReturnPlan(text=text.strip(), planned_at=planned, days=_rental_days(now, planned))

    if "завтра" in raw_text:
        planned = datetime.combine((now + timedelta(days=1)).date(), return_time)
        return ReturnPlan(text=text.strip(), planned_at=planned, days=_rental_days(now, planned))

    if "сегодня" in raw_text:
        planned = datetime.combine(now.date(), return_time)
        if planned <= now:
            planned += timedelta(days=1)
        return ReturnPlan(text=text.strip(), planned_at=planned, days=_rental_days(now, planned))

    numeric = re.search(r"\b(?P<day>\d{1,2})[./-](?P<month>\d{1,2})(?:[./-](?P<year>\d{2,4}))?\b", raw_text)
    if numeric:
        year = _normalize_year(numeric.group("year"), now.year)
        planned = _future_datetime(
            now,
            year,
            int(numeric.group("month")),
            int(numeric.group("day")),
            return_time,
            year_was_explicit=bool(numeric.group("year")),
        )
        return ReturnPlan(text=text.strip(), planned_at=planned, days=_rental_days(now, planned))

    word = re.search(r"\b(?P<day>\d{1,2})\s+(?P<month>[а-яё]+)(?:\s+(?P<year>\d{4}))?\b", raw_text)
    if word and word.group("month") in MONTHS:
        year = int(word.group("year")) if word.group("year") else now.year
        planned = _future_datetime(
            now,
            year,
            MONTHS[word.group("month")],
            int(word.group("day")),
            return_time,
            year_was_explicit=bool(word.group("year")),
        )
        return ReturnPlan(text=text.strip(), planned_at=planned, days=_rental_days(now, planned))

    return None


def _parse_time(text: str) -> time | None:
    match = re.search(r"\b(?P<hour>[01]?\d|2[0-3])[:.](?P<minute>[0-5]\d)\b", text)
    if not match:
        return None
    return time(int(match.group("hour")), int(match.group("minute")))


def _normalize_year(raw_year: str | None, current_year: int) -> int:
    if not raw_year:
        return current_year
    year = int(raw_year)
    return 2000 + year if year < 100 else year


def _future_datetime(
    now: datetime,
    year: int,
    month: int,
    day: int,
    return_time: time,
    year_was_explicit: bool,
) -> datetime:
    planned = datetime(year, month, day, return_time.hour, return_time.minute)
    if not year_was_explicit and planned <= now:
        planned = datetime(year + 1, month, day, return_time.hour, return_time.minute)
    return planned


def _rental_days(start: datetime, planned: datetime) -> int:
    return max(1, (planned.date() - start.date()).days)
