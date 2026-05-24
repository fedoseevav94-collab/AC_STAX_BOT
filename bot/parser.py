from __future__ import annotations

from dataclasses import dataclass
import re


TAKE_RE = re.compile(
    r"^\s*взял\s+(?P<model>.+?)\s+(?P<plate>[АВЕКМНОРСТУХABEKMHOPCTYX]\s?\d{3}\s?[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\s?\d{2,3})"
    r"\s+на\s+(?P<days>\d+)\s+д(?:ень|ня|ней|н[яе])"
    r"(?P<night>.*?ночн(?:ая|ую)\s+смен[ау])?"
    r".*?возврат\s+(?P<return_text>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)

RETURN_RE = re.compile(
    r"^\s*(?:вернул|сдал)\s+(?:(?P<model>.+?)\s+)?(?P<plate>[АВЕКМНОРСТУХABEKMHOPCTYX]\s?\d{3}\s?[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\s?\d{2,3})"
    r"(?:\s*,?\s*аренда\s+(?P<days>\d+)\s+д(?:ень|ня|ней|н[яе]))?(?P<comment>.*)\s*$",
    re.IGNORECASE | re.DOTALL,
)

APPROVAL_PAID_RE = re.compile(
    r"ставка\s*[-:]\s*(?P<rate>\d+).*?итого\s*[-:]\s*(?P<total>\d+).*?статус\s*:\s*(?P<status>.+)$",
    re.IGNORECASE | re.DOTALL,
)

APPROVAL_FREE_RE = re.compile(
    r"без\s+оплаты\s+аренды.*?статус(?:е)?\s+(?P<status>[А-ЯA-Z0-9 ._-]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TakeRequest:
    model: str
    plate: str
    days: int
    return_text: str
    is_night_shift: bool


@dataclass(frozen=True)
class ReturnRequest:
    model: str | None
    plate: str
    days: int | None
    comment: str


@dataclass(frozen=True)
class Approval:
    is_free: bool
    rate: int | None
    total: int | None
    status: str


def normalize_plate(plate: str) -> str:
    return re.sub(r"\s+", "", plate).upper()


def normalize_model(model: str) -> str:
    return re.sub(r"\s+", " ", model).strip().upper()


def parse_take(text: str) -> TakeRequest | None:
    match = TAKE_RE.match(text or "")
    if not match:
        return None
    return TakeRequest(
        model=normalize_model(match.group("model")),
        plate=normalize_plate(match.group("plate")),
        days=int(match.group("days")),
        return_text=match.group("return_text").strip(),
        is_night_shift=bool(match.group("night")),
    )


def parse_return(text: str) -> ReturnRequest | None:
    match = RETURN_RE.match(text or "")
    if not match:
        return None
    return ReturnRequest(
        model=normalize_model(match.group("model")) if match.group("model") else None,
        plate=normalize_plate(match.group("plate")),
        days=int(match.group("days")) if match.group("days") else None,
        comment=(match.group("comment") or "").strip(" ,\n"),
    )


def parse_approval(text: str) -> Approval | None:
    text = text or ""
    free_match = APPROVAL_FREE_RE.search(text)
    if free_match:
        return Approval(is_free=True, rate=None, total=None, status=free_match.group("status").strip())

    paid_match = APPROVAL_PAID_RE.search(text)
    if paid_match:
        return Approval(
            is_free=False,
            rate=int(paid_match.group("rate")),
            total=int(paid_match.group("total")),
            status=paid_match.group("status").strip(),
        )
    return None
