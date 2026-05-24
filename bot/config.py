from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


def _csv(value: str) -> set[str]:
    return {item.strip().lstrip("@").lower() for item in value.split(",") if item.strip()}


def _mapping(value: str, value_type: type[int] = int) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in value.split(","):
        if not item.strip():
            continue
        key, raw_value = item.split(":", 1)
        result[key.strip().upper()] = value_type(raw_value.strip())
    return result


@dataclass(frozen=True)
class Config:
    bot_token: str
    approver_usernames: set[str]
    admin_usernames: set[str]
    report_usernames: set[str]
    exempt_usernames: set[str]
    free_models: dict[str, int]
    driver_rates: dict[str, int]
    db_path: str
    work_chat_id: int | None
    media_group_wait_seconds: int


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не найден")
    raw_work_chat_id = os.getenv("WORK_CHAT_ID", "").strip()

    return Config(
        bot_token=token,
        approver_usernames=_csv(os.getenv("APPROVER_USERNAMES", "")),
        admin_usernames=_csv(os.getenv("ADMIN_USERNAMES", "")),
        report_usernames=_csv(os.getenv("REPORT_USERNAMES", "Fedos_AV,D_u_a")),
        exempt_usernames=_csv(os.getenv("EXEMPT_USERNAMES", "")),
        free_models=_mapping(os.getenv("FREE_MODELS", "JAC J7:10")),
        driver_rates=_mapping(os.getenv("DRIVER_RATES", "JAC J7:2400")),
        db_path=os.getenv("DB_PATH", "car_rental_bot.sqlite3"),
        work_chat_id=int(raw_work_chat_id) if raw_work_chat_id else None,
        media_group_wait_seconds=int(os.getenv("MEDIA_GROUP_WAIT_SECONDS", "3")),
    )
