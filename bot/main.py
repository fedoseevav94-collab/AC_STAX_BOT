from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta
from io import BytesIO
from collections import defaultdict
from dataclasses import dataclass, field, replace
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BufferedInputFile, CallbackQuery, InputMediaPhoto, Message
from aiogram.utils.backoff import BackoffConfig
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from bot.config import load_config
from bot.dates import parse_return_plan
from bot.keyboards import (
    admin_approval_controls,
    condition_menu,
    employee_reapproval_controls,
    model_by_index,
    model_category,
    model_legend,
    model_menu,
    return_plate_correction_controls,
    skip_take_comment_menu,
    start_menu,
    tariff_controls,
)
from bot.parser import is_valid_plate, normalize_plate, parse_approval, parse_return, parse_take
from bot.rules import check_take_rules, validate_approval
from bot.storage import Storage


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HELP_TEXT = """Форматы:

Взял JAC J7 Н537РА126 на 2 дня, возврат 29 августа
Взял KIA K5 Т339ВТ159, возврат завтра 18:30
Взял JAC J7 Н537РА126 на 1 день, ночная смена, возврат завтра

Возврат:
Вернул JAC J7 Н537РА126, аренда 2 дня

К выдаче и возврату нужно приложить 5 фото: 4 стороны авто и приборная панель с топливом.
"""

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DEFAULT_ADMIN_USERNAMES = {"fedos_av"}
PENDING_APPROVAL_STATUSES = {"pending", "resubmitted"}
REMINDER_BEFORE_RETURN = timedelta(hours=2)
REMINDER_CHECK_INTERVAL_SECONDS = 300
AUTO_APPROVAL_AFTER = timedelta(minutes=15)
AUTO_APPROVAL_CHECK_INTERVAL_SECONDS = 60
HALF_DAY_MIN_HOURS = 10
HALF_DAY_MAX_HOURS = 16
POLLING_BACKOFF = BackoffConfig(min_delay=2.0, max_delay=30.0, factor=1.5, jitter=0.2)
DEFAULT_TARIFFS = {
    "comfort_day": 1700,
    "comfort_half": 900,
    "economy_day": 1200,
    "economy_half": 600,
}
TARIFF_LABELS = {
    "comfort_day": "Комфорт/Комфорт+ сутки",
    "comfort_half": "Комфорт/Комфорт+ 12 часов",
    "economy_day": "Эконом сутки",
    "economy_half": "Эконом 12 часов",
}


class TakeFlow(StatesGroup):
    model = State()
    plate = State()
    return_text = State()
    comment = State()
    photos = State()


class ProfileFlow(StatesGroup):
    name = State()


class ReturnFlow(StatesGroup):
    plate = State()
    condition = State()
    photos = State()


class ReturnPlateCorrectionFlow(StatesGroup):
    plate = State()


class AdminRestoreFlow(StatesGroup):
    plate = State()


class TestDriveFlow(StatesGroup):
    model = State()
    plate = State()
    comment = State()
    photos = State()


class AdminAmountFlow(StatesGroup):
    amount = State()


class AdminTariffFlow(StatesGroup):
    amount = State()


@dataclass
class MediaGroupBuffer:
    messages: list[Message] = field(default_factory=list)
    task: asyncio.Task | None = None


config = load_config()
storage = Storage(config.db_path)
dp = Dispatcher(storage=MemoryStorage())
media_groups: dict[str, MediaGroupBuffer] = defaultdict(MediaGroupBuffer)


def username(message: Message) -> str | None:
    return message.from_user.username.lower() if message.from_user and message.from_user.username else None


def callback_username(callback: CallbackQuery) -> str | None:
    return callback.from_user.username.lower() if callback.from_user and callback.from_user.username else None


def now_moscow() -> datetime:
    return datetime.now(MOSCOW_TZ).replace(tzinfo=None)


def previous_month_text() -> str:
    current = now_moscow()
    first_day = current.replace(day=1)
    previous_month_last_day = first_day - timedelta(days=1)
    return previous_month_last_day.strftime("%Y-%m")


def remember_user(user) -> None:
    if user and user.username:
        storage.set_setting(f"user_id:{user.username.lower()}", str(user.id))


def admin_control_usernames() -> set[str]:
    return DEFAULT_ADMIN_USERNAMES | config.admin_usernames


def is_admin_control_user(callback: CallbackQuery) -> bool:
    return (callback_username(callback) or "") in admin_control_usernames()


def is_test_drive_rental(rental) -> bool:
    return int(rental.days or 0) == 0 or rental.condition_status == "test_drive" or rental.approval_status == "test_drive"


def is_test_drive_row(row) -> bool:
    return (
        int(row["days"] or 0) == 0
        or row["condition_status"] == "test_drive"
        or row["approval_status"] == "test_drive"
    )


def employee_name(message: Message) -> str:
    if not message.from_user:
        return "Неизвестный сотрудник"
    saved_name = storage.get_employee_name(message.from_user.id)
    if saved_name:
        return saved_name
    return message.from_user.full_name


def has_employee_name(user) -> bool:
    saved_name = storage.get_employee_name(user.id)
    if saved_name:
        return True
    full_name = " ".join((user.full_name or "").split())
    if not full_name or full_name.lower() == (user.username or "").lower():
        return False
    return len(full_name.split()) >= 2


def is_approver(message: Message) -> bool:
    user_name = username(message) or ""
    return user_name in config.approver_usernames or user_name in admin_control_usernames()


def is_report_user(message: Message) -> bool:
    return is_admin_message(message)


def is_report_callback(callback: CallbackQuery) -> bool:
    return is_admin_control_user(callback)


def is_admin_message(message: Message) -> bool:
    return (username(message) or "") in admin_control_usernames()


def is_admin_user_obj(user) -> bool:
    return bool(user and user.username and user.username.lower() in admin_control_usernames())


def is_rental_waiting_approval(rental) -> bool:
    return (rental.approval_status or "pending") in PENDING_APPROVAL_STATUSES


def is_rental_returnable(rental) -> bool:
    return rental.status == "taken" and not is_rental_waiting_approval(rental) and rental.approval_status not in {
        "rejected",
        "employee_cancelled",
    }


def return_plate_block_message(plate: str, rentals: list) -> str | None:
    returnable = [rental for rental in rentals if is_rental_returnable(rental)]
    if len(returnable) == 1:
        return None
    if len(returnable) > 1:
        return (
            f"По номеру {plate} найдено несколько активных выдач. "
            "Обратитесь к ответственному, чтобы он проверил выдачи вручную."
        )
    if not rentals:
        return f"По номеру {plate} не нашел выдачу. Проверьте номер или обратитесь к ответственному."

    latest = rentals[0]
    if latest.status == "returned":
        return returned_rental_details(plate, latest)
    if is_rental_waiting_approval(latest):
        return (
            f"Выдача по номеру {plate} есть, но она еще ждет одобрения. "
            "Сдать авто можно после одобрения или автоодобрения через 15 минут."
        )
    if latest.approval_status == "rejected":
        return f"Заявка по номеру {plate} не одобрена. Обратитесь к ответственному."
    if latest.approval_status == "employee_cancelled":
        return f"Заявка по номеру {plate} отменена сотрудником. Обратитесь к ответственному."
    return f"По номеру {plate} не нашел активную выдачу. Обратитесь к ответственному."


def photo_count(messages: list[Message]) -> int:
    return sum(1 for message in messages if message.photo)


def photo_file_ids(messages: list[Message]) -> list[str]:
    return [message.photo[-1].file_id for message in messages if message.photo]


async def send_to_work_chat(bot: Bot, file_ids: list[str], summary: str) -> list[Message]:
    work_chat_id = effective_work_chat_id()
    if work_chat_id is None:
        return []
    try:
        if not file_ids:
            message = await bot.send_message(chat_id=work_chat_id, text=summary)
            return [message]
        media = [
            InputMediaPhoto(media=file_id, caption=summary if index == 0 else None)
            for index, file_id in enumerate(file_ids)
        ]
        return await bot.send_media_group(chat_id=work_chat_id, media=media)
    except Exception:
        logger.exception("Failed to send message to work chat %s", work_chat_id)
        return []


async def publish_rental_to_work_chat(bot: Bot, rental) -> bool:
    is_test_drive = is_test_drive_rental(rental)
    public_no = rental.rental_no or rental.id
    title = f"Тест драйв #{public_no}" if is_test_drive else f"Выдача #{public_no}"
    comment = (
        f"Согласовано: {comment_text(rental.return_comment)}"
        if is_test_drive
        else rental.take_comment
    )
    sent_messages = await send_to_work_chat(
        bot,
        storage.get_rental_photo_file_ids(rental.id),
        format_application(
            title,
            rental.employee_name or "Без ФИО",
            rental.username,
            rental.user_id,
            rental.model,
            rental.plate,
            rental.created_at,
            rental.planned_return_at,
            rental.return_text,
            rental.days,
            comment,
            0 if is_test_drive else rental.total,
        ),
    )
    return bool(sent_messages)


def work_chat_delivery_text(sent_messages: list[Message]) -> str:
    if sent_messages:
        return "Фото отправлены в рабочий чат."
    if effective_work_chat_id() is None:
        return "Рабочий чат не задан, фото никуда не отправлены."
    return "Не удалось отправить фото в рабочий чат. Проверьте настройки и логи бота."


def approval_message_setting_key(rental_id: int, admin_username: str) -> str:
    return f"approval_message:{rental_id}:{admin_username}"


def auto_approval_admin_text(rental, sent_to_work_chat: bool) -> str:
    return (
        f"Заявка #{rental.rental_no or rental.id} одобрена автоматически через 15 минут.\n"
        f"{rental.employee_name or 'Без ФИО'}: {rental.model} {rental.plate}\n"
        f"Сумма: {0 if is_test_drive_rental(rental) else (rental.total or 0)} руб.\n"
        + ("Заявка отправлена в рабочий чат." if sent_to_work_chat else "Заявка не отправлена в рабочий чат, проверьте настройки и логи бота.")
    )


async def mark_admin_approval_messages_auto_approved(bot: Bot, rental, sent_to_work_chat: bool) -> None:
    text = auto_approval_admin_text(rental, sent_to_work_chat)
    for admin_username in admin_control_usernames():
        admin_user_id = storage.get_setting(f"user_id:{admin_username}")
        message_id = storage.get_setting(approval_message_setting_key(rental.id, admin_username))
        if not admin_user_id or not message_id:
            continue
        try:
            await bot.edit_message_text(
                chat_id=int(admin_user_id),
                message_id=int(message_id),
                text=text,
                reply_markup=None,
            )
        except Exception:
            logger.exception("Failed to mark admin approval message as auto approved for rental %s", rental.id)


async def send_admin_approval_request(bot: Bot, rental, note: str = "Новая заявка на согласование.") -> bool:
    is_test_drive = is_test_drive_rental(rental)
    public_no = rental.rental_no or rental.id
    title = f"Тест драйв #{public_no}" if is_test_drive else f"Выдача #{public_no}"
    comment = (
        f"Согласовано: {comment_text(rental.return_comment)}"
        if is_test_drive
        else rental.take_comment
    )
    sent = False
    for admin_username in admin_control_usernames():
        admin_user_id = storage.get_setting(f"user_id:{admin_username}")
        if not admin_user_id:
            continue
        try:
            message = await bot.send_message(
                chat_id=int(admin_user_id),
                text="\n\n".join(
                    [
                        note,
                        format_application(
                            title,
                            rental.employee_name or "Без ФИО",
                            rental.username,
                            rental.user_id,
                            rental.model,
                            rental.plate,
                            rental.created_at,
                            rental.planned_return_at,
                            rental.return_text,
                            rental.days,
                            comment,
                            0 if is_test_drive else rental.total,
                        ),
                    ]
                ),
                reply_markup=admin_approval_controls(rental.id),
            )
            storage.set_setting(approval_message_setting_key(rental.id, admin_username), str(message.message_id))
            sent = True
        except Exception:
            logger.exception("Failed to send approval request to admin %s for rental %s", admin_username, rental.id)
    return sent


def effective_work_chat_id() -> int | None:
    if config.work_chat_id is not None:
        return config.work_chat_id
    value = storage.get_setting("work_chat_id")
    return int(value) if value else None


def tariff_value(key: str) -> int:
    value = storage.get_setting(f"tariff:{key}")
    if value and value.isdigit():
        return int(value)
    return DEFAULT_TARIFFS[key]


def tariff_summary_text() -> str:
    return "\n".join(
        [
            "Текущие тарифы:",
            f"{TARIFF_LABELS['comfort_day']}: {tariff_value('comfort_day')} руб.",
            f"{TARIFF_LABELS['comfort_half']}: {tariff_value('comfort_half')} руб.",
            f"{TARIFF_LABELS['economy_day']}: {tariff_value('economy_day')} руб.",
            f"{TARIFF_LABELS['economy_half']}: {tariff_value('economy_half')} руб.",
        ]
    )


def rental_price(model: str, days: int, planned_return_at: str | None, started_at: str | None = None) -> tuple[int, int]:
    category = model_category(model)
    day_rate = tariff_value("economy_day") if category == "ЭКОНОМ" else tariff_value("comfort_day")
    half_day_rate = tariff_value("economy_half") if category == "ЭКОНОМ" else tariff_value("comfort_half")
    normalized_days = max(1, int(days or 1))

    if planned_return_at:
        try:
            start = datetime.fromisoformat(started_at) if started_at else now_moscow()
            planned = datetime.fromisoformat(planned_return_at)
            hours = (planned - start).total_seconds() / 3600
            if HALF_DAY_MIN_HOURS <= hours <= HALF_DAY_MAX_HOURS:
                return half_day_rate, half_day_rate
        except ValueError:
            pass

    return day_rate, day_rate * normalized_days


def format_dt(value: str | None) -> str:
    if not value:
        return "не указана"
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def user_label(full_name: str, user_name: str | None, user_id: int) -> str:
    nick = f"@{user_name}" if user_name else f"id {user_id}"
    return f"{full_name} ({nick})"


def actor_label(full_name: str | None, user_name: str | None, user_id: int | None) -> str:
    if user_id is not None:
        return user_label(full_name or "Без ФИО", user_name, user_id)
    if user_name:
        return f"{full_name or 'Без ФИО'} (@{user_name})"
    return full_name or "не указано"


def returned_rental_details(plate: str, rental) -> str:
    if is_test_drive_rental(rental):
        closer_name = rental.return_employee_name or rental.employee_name
        closer_username = rental.return_username or rental.username
        closer_user_id = rental.return_user_id or rental.user_id
        return "\n".join(
            [
                f"По номеру {plate} последняя запись уже закрыта как тест-драйв.",
                f"Тест-драйв #{rental.rental_no or rental.id} от {format_dt(rental.created_at)}.",
                f"Оформлял: {actor_label(rental.employee_name, rental.username, rental.user_id)}.",
                f"Закрыл тест-драйв: {actor_label(closer_name, closer_username, closer_user_id)}.",
                "Если машину нужно сдать через сценарий сдачи, сначала нажмите в админ-меню `Восстановить выдачу`.",
            ]
        )
    return "\n".join(
        [
            f"По номеру {plate} последняя выдача уже отмечена как сданная.",
            f"Выдача #{rental.rental_no or rental.id} от {format_dt(rental.created_at)}.",
            f"Брал: {actor_label(rental.employee_name, rental.username, rental.user_id)}.",
            f"Сдача отмечена: {format_dt(rental.returned_at)}.",
            f"Закрывал сдачу: {actor_label(rental.return_employee_name, rental.return_username, rental.return_user_id)}.",
        ]
    )


def return_preview_rental(
    rental,
    message_id: int,
    plate: str,
    return_comment: str | None,
    condition_status: str | None,
    user_id: int | None,
    user_name: str | None,
    full_name: str | None,
):
    return replace(
        rental,
        return_message_id=message_id,
        return_plate=normalize_plate(plate),
        return_comment=return_comment,
        condition_status=condition_status,
        status="returned",
        returned_at=now_moscow().isoformat(timespec="seconds"),
        return_user_id=user_id,
        return_username=user_name,
        return_employee_name=full_name,
    )


def comment_text(comment: str | None) -> str:
    return comment.strip() if comment and comment.strip() else "не указано"


def report_comment(take_comment: str | None, return_comment: str | None) -> str:
    parts = []
    if take_comment and take_comment.strip():
        parts.append(f"Взятие: {take_comment.strip()}")
    if return_comment and return_comment.strip():
        parts.append(f"Сдача: {return_comment.strip()}")
    return "\n".join(parts)


def report_comment_for_row(row) -> str:
    comment = report_comment(row["take_comment"], row["return_comment"])
    if is_test_drive_row(row):
        return f"Тест-драйв\n{comment}".strip()
    return comment


def report_days(days: int) -> str | int:
    return "тест драйв" if int(days or 0) == 0 else days


def format_application(
    title: str,
    full_name: str,
    user_name: str | None,
    user_id: int,
    model: str,
    plate: str,
    created_at: str | None,
    planned_return_at: str | None,
    return_text: str | None,
    days: int,
    comment: str | None,
    total: int | None,
) -> str:
    planned = format_dt(planned_return_at) if planned_return_at else (return_text or "не указана")
    amount = f"{total} руб." if total is not None else "не рассчитана"
    return "\n".join(
        [
            title,
            f"ФИО: {user_label(full_name, user_name, user_id)}",
            f"Гос номер авто: {plate}",
            f"Марка модель: {model}",
            f"Дата взятия: {format_dt(created_at)}",
            f"Планируемая дата возврата: {planned}",
            f"Кол-во дней: {report_days(days)}",
            f"Комментарий: {comment_text(comment)}",
            f"Сумма аренды: {amount}",
        ]
    )


def format_return_application(rental, comment: str | None = None, model: str | None = None, days: int | None = None) -> str:
    full_name = rental.return_employee_name or rental.employee_name or "Без ФИО"
    user_name = rental.return_username or rental.username
    user_id = rental.return_user_id or rental.user_id
    text = format_application(
        f"Сдача #{rental.rental_no or rental.id}",
        full_name,
        user_name,
        user_id,
        model or rental.model,
        rental.return_plate or rental.plate,
        rental.created_at,
        rental.planned_return_at,
        rental.return_text,
        days if days is not None else rental.days,
        comment if comment is not None else rental.return_comment,
        rental.total,
    )
    if rental.return_user_id and rental.return_user_id != rental.user_id:
        text += "\n\nВнимание: авто сдал другой сотрудник."
        text += f"\nВыдачу оформлял: {user_label(rental.employee_name or 'Без ФИО', rental.username, rental.user_id)}"
        text += f"\nСдачу оформил: {user_label(full_name, user_name, user_id)}"
    return text


async def send_return_plate_correction_control(bot: Bot, rental) -> None:
    work_chat_id = effective_work_chat_id()
    if work_chat_id is None:
        return
    try:
        await bot.send_message(
            chat_id=work_chat_id,
            text=f"Сдача #{rental.rental_no or rental.id}: если госномер указан неверно, ответственный за сдачу может исправить его.",
            reply_markup=return_plate_correction_controls(rental.id),
        )
    except Exception:
        logger.exception("Failed to send return plate correction control for rental %s", rental.id)


def active_rental_line(rental, now: datetime | None = None) -> str:
    planned = format_dt(rental.planned_return_at)
    left_text = ""
    if rental.planned_return_at:
        try:
            planned_dt = datetime.fromisoformat(rental.planned_return_at)
            current = now or now_moscow()
            delta = planned_dt - current
            if delta.total_seconds() < 0:
                hours = abs(delta.total_seconds()) / 3600
                left_text = f", просрочка {hours:.1f} ч."
            else:
                hours = delta.total_seconds() / 3600
                left_text = f", осталось {hours:.1f} ч."
        except ValueError:
            pass
    username_text = f"@{rental.username}" if rental.username else f"id {rental.user_id}"
    return (
        f"#{rental.rental_no or rental.id}: {rental.employee_name or 'Без ФИО'} ({username_text}) - "
        f"{rental.model} {rental.plate}, возврат {planned}{left_text}"
    )


def active_rentals_text() -> str:
    rentals = storage.active_rentals()
    if not rentals:
        return "Активных выдач сейчас нет."
    current = now_moscow()
    lines = [f"Активные выдачи: {len(rentals)}"]
    lines.extend(active_rental_line(rental, current) for rental in rentals)
    return "\n".join(lines)


def restore_rental_by_plate_text(plate_text: str) -> str:
    plate = normalize_plate(plate_text)
    if not is_valid_plate(plate):
        return "Не понял госномер. Введите номер в формате А123ВС77 или А123ВС777, например: В820НУ172."
    rental = storage.restore_latest_returned_by_plate(plate)
    if rental is None:
        return f"По номеру {plate} не нашел закрытую выдачу или тест-драйв, которые можно восстановить."
    title = "Тест-драйв" if is_test_drive_rental(rental) else "Выдача"
    return "\n".join(
        [
            f"{title} #{rental.rental_no or rental.id} восстановлен в активные.",
            f"Авто: {rental.model} {rental.plate}",
            f"Брал: {actor_label(rental.employee_name, rental.username, rental.user_id)}",
            f"Дата выдачи: {format_dt(rental.created_at)}",
        ]
    )


async def process_messages(messages: list[Message]) -> None:
    text_message = next((message for message in messages if message.caption or message.text), messages[0])
    text = text_message.caption or text_message.text or ""
    photos = photo_count(messages)
    if text_message.from_user:
        remember_user(text_message.from_user)

    take = parse_take(text)
    if take:
        if text_message.from_user is None:
            await text_message.reply("Не могу оформить выдачу без Telegram-пользователя. Напишите боту обычным аккаунтом.")
            return
        if photos < 5:
            await text_message.reply(
                f"Для выдачи нужно 5 фото: 4 стороны авто и приборная панель с топливом. Сейчас вижу: {photos}. "
                "Заявку не фиксирую, пришлите полный комплект через /car."
            )
            return
        started_at = now_moscow()
        plan = parse_return_plan(take.return_text, now=started_at)
        if plan is None:
            await text_message.reply(
                "Не понял дату возврата. Напишите, например: завтра 18:30, 29 августа 20:00 или 29.08.2026 12:00."
            )
            return
        started_at_text = started_at.isoformat(timespec="seconds")
        check = check_take_rules(config, replace(take, days=plan.days), username(text_message))
        rate, total = rental_price(
            take.model,
            plan.days,
            plan.planned_at.isoformat(timespec="seconds"),
            started_at_text,
        )
        rental_id = storage.create_take(
            chat_id=text_message.chat.id,
            message_id=text_message.message_id,
            user_id=text_message.from_user.id,
            username=username(text_message),
            employee_name=employee_name(text_message),
            model=take.model,
            plate=take.plate,
            days=plan.days,
            return_text=plan.text,
            planned_return_at=plan.planned_at.isoformat(timespec="seconds"),
            night_shift=take.is_night_shift,
            photo_count=photos,
            take_comment=None,
            rate=rate,
            total=total,
            created_at=started_at_text,
        )
        rental = storage.get_by_id(rental_id)
        storage.set_rental_photo_file_ids(rental_id, photo_file_ids(messages))
        public_no = rental.rental_no if rental and rental.rental_no else rental_id
        notes = [f"Зафиксировал выдачу #{public_no}: {take.model} {take.plate}, {plan.days} дн., сумма {total} руб."]
        if not check.allowed:
            notes.append("По правилам выдача не проходит: " + " ".join(check.warnings))
        elif check.warnings:
            notes.extend(check.warnings)
        if rental:
            admin_sent = await send_admin_approval_request(text_message.bot, rental)
            notes.append(
                "Заявка отправлена на согласование."
                if admin_sent
                else "Заявка сохранена, но админ еще не запускал бота в личке. Напишите ответственному."
            )
        summary = await text_message.reply("\n".join(notes))
        storage.update_take_message_id(rental_id, summary.message_id)
        return

    returned = parse_return(text)
    if returned:
        block_message = return_plate_block_message(returned.plate, storage.rentals_by_plate(returned.plate))
        if block_message:
            await text_message.reply(block_message)
            return
        if photos < 5:
            await text_message.reply(
                f"Для возврата нужно 5 фото: 4 стороны авто и приборная панель с топливом. Сейчас вижу: {photos}. "
                "Возврат не фиксирую, пришлите полный комплект через /car."
            )
            return
        if not returned.comment:
            await text_message.reply(
                "Для возврата нужен комментарий о недостатках или отметка `Машина полностью исправна` в сценарии /car. "
                "Возврат не фиксирую."
            )
            return
        return_user_id = text_message.from_user.id if text_message.from_user else None
        return_username = username(text_message)
        return_employee_name = employee_name(text_message)
        candidate = storage.find_return_candidate(returned.plate, return_user_id)
        if candidate is None:
            await text_message.reply("Не нашел активную выдачу по этому номеру. Проверьте номер или формат.")
            return
        model = returned.model or candidate.model
        days = returned.days or candidate.days
        preview = return_preview_rental(
            candidate,
            text_message.message_id,
            returned.plate,
            returned.comment or None,
            "comment" if returned.comment else None,
            return_user_id,
            return_username,
            return_employee_name,
        )
        sent_messages = await send_to_work_chat(
            text_message.bot,
            photo_file_ids(messages),
            format_return_application(preview, comment=returned.comment, model=model, days=days),
        )
        if not sent_messages:
            await text_message.reply(
                work_chat_delivery_text(sent_messages) + "\nВозврат не зафиксирован. Попробуйте позже через /car."
            )
            return
        rental = storage.mark_returned(
            text_message.chat.id,
            text_message.message_id,
            returned.plate,
            photos,
            return_comment=returned.comment or None,
            condition_status="comment" if returned.comment else None,
            user_id=return_user_id,
            username=return_username,
            employee_name=return_employee_name,
        )
        if rental is None:
            await text_message.reply("Фото отправлены в рабочий чат, но выдача уже изменилась. Обратитесь к ответственному.")
            return
        notes = [f"Зафиксировал возврат: {model} {returned.plate}, аренда {days} дн., сумма {rental.total or 0} руб."]
        notes.append(work_chat_delivery_text(sent_messages))
        storage.update_return_work_message(
            rental.id,
            sent_messages[0].chat.id,
            sent_messages[0].message_id,
            [sent.message_id for sent in sent_messages],
        )
        rental = storage.get_by_id(rental.id) or rental
        await send_return_plate_correction_control(text_message.bot, rental)
        if rental.total and rental.total > 0:
            notes.append("После списания аренды отправьте /paid ответом на сообщение возврата.")
        summary = await text_message.reply("\n".join(notes))
        storage.update_return_message_id(rental.id, summary.message_id)
        return

    normalized_text = text.strip().lower()
    if normalized_text.startswith(("взял", "сдал", "вернул")):
        await text_message.reply(
            "Не понял госномер. Напишите номер в формате А123ВС77 или А123ВС777, например: Н537РА126."
        )


async def flush_media_group(media_group_id: str) -> None:
    await asyncio.sleep(config.media_group_wait_seconds)
    buffer = media_groups.pop(media_group_id, None)
    if buffer:
        await process_messages(buffer.messages)


@dp.message(Command("help"))
async def help_command(message: Message) -> None:
    if message.from_user:
        remember_user(message.from_user)
    await message.answer(HELP_TEXT)


@dp.message(Command("start"))
async def start_command(message: Message) -> None:
    if message.from_user:
        remember_user(message.from_user)
    await message.answer("Выберите действие:", reply_markup=start_menu(is_report_user(message), is_admin_user_obj(message.from_user)))


@dp.message(Command("car"))
async def car_command(message: Message) -> None:
    if message.from_user:
        remember_user(message.from_user)
    await message.answer("Выберите действие:", reply_markup=start_menu(is_report_user(message), is_admin_user_obj(message.from_user)))


@dp.message(Command("status"))
async def status_command(message: Message) -> None:
    await message.answer(f"Активных аренд сейчас: {storage.active_count()}")


@dp.message(Command("active_rentals"))
async def active_rentals_command(message: Message) -> None:
    if not is_report_user(message):
        await message.reply("Список активных выдач может запросить только пользователь с доступом к отчетам.")
        return
    await message.answer(active_rentals_text())


@dp.message(Command("restore_rental"))
async def restore_rental_command(message: Message) -> None:
    if not is_admin_message(message):
        await message.reply("Восстановить выдачу может только администратор.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Укажите госномер: `/restore_rental В820НУ172`.")
        return
    await message.answer(restore_rental_by_plate_text(parts[1]))


@dp.message(Command("tariffs"))
async def tariffs_command(message: Message) -> None:
    if not is_admin_message(message):
        await message.reply("Тарифы может менять только администратор.")
        return
    await message.answer(tariff_summary_text(), reply_markup=tariff_controls())


@dp.message(Command("chat_id"))
async def chat_id_command(message: Message) -> None:
    await message.answer(f"ID этого чата: {message.chat.id}")


@dp.message(Command("set_work_chat"))
async def set_work_chat_command(message: Message) -> None:
    if not is_report_user(message):
        await message.reply("Рабочий чат может назначить только пользователь с доступом к отчетам.")
        return
    storage.set_setting("work_chat_id", str(message.chat.id))
    await message.answer(f"Готово. Этот чат назначен рабочим для пересылки фото и сводок: {message.chat.id}")


@dp.message(Command("report_month"))
async def report_month_command(message: Message) -> None:
    if not is_report_user(message):
        await message.reply("Отчет может запросить только пользователь с доступом к отчетам.")
        return

    parts = (message.text or "").split()
    year_month = parts[1] if len(parts) > 1 else now_moscow().strftime("%Y-%m")
    rows = storage.monthly_report_rows(year_month)
    data = build_report_xlsx(rows, year_month)
    await message.answer_document(
        BufferedInputFile(data, filename=f"car-rentals-{year_month}.xlsx"),
        caption=f"Отчет за {year_month}: {len(rows)} записей.",
    )


@dp.message(Command("report_employee"))
async def report_employee_command(message: Message) -> None:
    if not is_report_user(message):
        await message.reply("Отчет может запросить только пользователь с доступом к отчетам.")
        return

    parts = (message.text or "").split(maxsplit=2)
    year_month = now_moscow().strftime("%Y-%m")
    query = ""
    if len(parts) >= 2:
        if len(parts[1]) == 7 and parts[1][4] == "-":
            year_month = parts[1]
            query = parts[2] if len(parts) == 3 else ""
        else:
            query = " ".join(parts[1:])
    if not query:
        await message.reply("Укажите сотрудника: `/report_employee 2026-05 @username` или `/report_employee Иван Иванов`.")
        return

    rows = storage.monthly_report_rows(year_month, query)
    data = build_report_xlsx(rows, year_month)
    safe_query = query.strip().lstrip("@").replace(" ", "_")[:40] or "employee"
    await message.answer_document(
        BufferedInputFile(data, filename=f"car-rentals-{year_month}-{safe_query}.xlsx"),
        caption=f"Отчет по сотруднику за {year_month}: {len(rows)} записей.",
    )


@dp.message(Command("employees"))
async def employees_command(message: Message) -> None:
    if not is_report_user(message):
        await message.reply("Список может запросить только пользователь с доступом к отчетам.")
        return

    parts = (message.text or "").split()
    year_month = parts[1] if len(parts) > 1 else now_moscow().strftime("%Y-%m")
    rows = storage.employees_for_month(year_month)
    if not rows:
        await message.reply(f"За {year_month} сотрудников с арендой не нашел.")
        return

    lines = [f"Сотрудники с арендой за {year_month}:"]
    for row in rows:
        username_text = f"@{row['username']}" if row["username"] else f"id {row['user_id']}"
        lines.append(
            f"{row['employee_name'] or 'Без ФИО'} ({username_text}) - "
            f"{row['rentals_count']} аренд, {row['total_days']} дн."
        )
    await message.answer("\n".join(lines))


@dp.callback_query(F.data == "report:month")
async def report_month_button(callback: CallbackQuery) -> None:
    if not is_report_callback(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    year_month = now_moscow().strftime("%Y-%m")
    rows = storage.monthly_report_rows(year_month)
    data = build_report_xlsx(rows, year_month)
    await callback.message.answer_document(
        BufferedInputFile(data, filename=f"car-rentals-{year_month}.xlsx"),
        caption=f"Отчет за {year_month}: {len(rows)} записей.",
    )
    await callback.answer()


@dp.callback_query(F.data == "report:previous_month")
async def report_previous_month_button(callback: CallbackQuery) -> None:
    if not is_report_callback(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    year_month = previous_month_text()
    rows = storage.monthly_report_rows(year_month)
    data = build_report_xlsx(rows, year_month)
    await callback.message.answer_document(
        BufferedInputFile(data, filename=f"car-rentals-{year_month}.xlsx"),
        caption=f"Отчет за прошлый месяц ({year_month}): {len(rows)} записей.",
    )
    await callback.answer()


@dp.callback_query(F.data == "report:employees")
async def employees_button(callback: CallbackQuery) -> None:
    if not is_report_callback(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    year_month = now_moscow().strftime("%Y-%m")
    rows = storage.employees_for_month(year_month)
    if not rows:
        await callback.message.answer(f"За {year_month} сотрудников с арендой не нашел.")
        await callback.answer()
        return
    lines = [f"Сотрудники с арендой за {year_month}:"]
    for row in rows:
        username_text = f"@{row['username']}" if row["username"] else f"id {row['user_id']}"
        lines.append(
            f"{row['employee_name'] or 'Без ФИО'} ({username_text}) - "
            f"{row['rentals_count']} аренд, {row['total_days']} дн."
        )
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@dp.callback_query(F.data == "report:employee_help")
async def report_employee_help_button(callback: CallbackQuery) -> None:
    if not is_report_callback(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.message.answer(
        "Для выгрузки по сотруднику отправьте команду:\n"
        "`/report_employee 2026-05 @username`\n"
        "или\n"
        "`/report_employee Иван Иванов`"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin:active_rentals")
async def active_rentals_button(callback: CallbackQuery) -> None:
    if not is_report_callback(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.message.answer(active_rentals_text())
    await callback.answer()


@dp.callback_query(F.data == "admin:tariffs")
async def tariffs_button(callback: CallbackQuery) -> None:
    if not is_admin_control_user(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.message.answer(tariff_summary_text(), reply_markup=tariff_controls())
    await callback.answer()


@dp.callback_query(F.data == "admin:restore_returned")
async def restore_returned_button(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin_control_user(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminRestoreFlow.plate)
    await callback.message.answer("Введите госномер выдачи, которую нужно вернуть в активные, например: В820НУ172")
    await callback.answer()


@dp.message(AdminRestoreFlow.plate)
async def restore_returned_plate(message: Message, state: FSMContext) -> None:
    if not is_admin_message(message):
        await message.answer("Восстановить выдачу может только администратор.")
        await state.clear()
        return
    await message.answer(restore_rental_by_plate_text(message.text or ""))
    await state.clear()


@dp.callback_query(F.data.startswith("tariff:set:"))
async def tariff_set_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin_control_user(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    tariff_key = callback.data.rsplit(":", 1)[1]
    if tariff_key not in DEFAULT_TARIFFS:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await state.update_data(tariff_key=tariff_key)
    await state.set_state(AdminTariffFlow.amount)
    await callback.message.answer(
        f"Введите новую сумму для тарифа `{TARIFF_LABELS[tariff_key]}` одним числом, например: 1700"
    )
    await callback.answer()


@dp.message(AdminTariffFlow.amount)
async def tariff_set_finish(message: Message, state: FSMContext) -> None:
    if not is_admin_message(message):
        await message.answer("Недостаточно прав.")
        await state.clear()
        return
    raw_amount = (message.text or "").strip().replace(" ", "")
    if not raw_amount.isdigit():
        await message.answer("Введите сумму одним числом, например: 1700")
        return
    data = await state.get_data()
    tariff_key = data.get("tariff_key")
    if tariff_key not in DEFAULT_TARIFFS:
        await message.answer("Тариф не найден. Откройте настройки тарифов заново.")
        await state.clear()
        return
    storage.set_setting(f"tariff:{tariff_key}", raw_amount)
    await state.clear()
    await message.answer(
        f"Тариф `{TARIFF_LABELS[tariff_key]}` изменен на {int(raw_amount)} руб.\n\n{tariff_summary_text()}",
        reply_markup=tariff_controls(),
    )


def build_report_xlsx(rows, year_month: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Аренды"
    headers = [
        "ФИО",
        "Марка модель машины",
        "Гос номер",
        "Дата взятия",
        "Дата сдачи",
        "Кол-во дней",
        "Сумма аренды",
        "Комментарий",
    ]
    sheet.append([f"Отчет по арендам за {year_month}"])
    sheet.append(headers)
    for row in rows:
        is_test_drive = is_test_drive_row(row)
        _, calculated_total = rental_price(
            row["model"],
            row["days"],
            row["planned_return_at"],
            row["created_at"],
        )
        sheet.append(
            [
                row["employee_name"] or "",
                row["model"],
                row["plate"],
                format_dt(row["created_at"]),
                format_dt(row["returned_at"]),
                report_days(row["days"]),
                0 if is_test_drive else (row["total"] if row["total"] is not None else calculated_total),
                report_comment_for_row(row),
            ]
        )

    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    sheet["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="1F4E78")
    sheet["A1"].alignment = Alignment(horizontal="center")
    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in sheet[2]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in sheet.iter_rows(min_row=3):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A3"
    sheet.auto_filter.ref = f"A2:{get_column_letter(len(headers))}{sheet.max_row}"
    widths = [28, 24, 16, 20, 20, 12, 16, 42]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@dp.message(Command("paid"))
async def paid_command(message: Message) -> None:
    if not is_approver(message):
        await message.reply("Отметить списание может только согласующий или администратор.")
        return
    if not message.reply_to_message:
        await message.reply("Команду /paid нужно отправить ответом на сообщение о возврате.")
        return
    ok = storage.mark_paid_by_return_message(message.chat.id, message.reply_to_message.message_id)
    await message.reply("Списание отмечено." if ok else "Не нашел возврат по сообщению, на которое вы ответили.")


@dp.callback_query(F.data.startswith("rent:approve:"))
async def admin_approve_rental(callback: CallbackQuery) -> None:
    if not is_admin_control_user(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    rental_id = int(callback.data.rsplit(":", 1)[1])
    current_rental = storage.get_by_id(rental_id)
    if current_rental is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not is_rental_waiting_approval(current_rental):
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return
    rental = storage.approve_waiting(rental_id, "approved")
    if rental is None:
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return
    sent_to_work_chat = await publish_rental_to_work_chat(callback.message.bot, rental)
    await callback.message.edit_text(
        f"Заявка #{rental.rental_no or rental.id} одобрена"
        f"{' и отправлена в рабочий чат' if sent_to_work_chat else ', но не отправлена в рабочий чат'}.\n"
        f"{rental.employee_name or 'Без ФИО'}: {rental.model} {rental.plate}\n"
        f"Сумма: {0 if is_test_drive_rental(rental) else (rental.total or 0)} руб."
    )
    await callback.answer("Одобрено")


@dp.callback_query(F.data.startswith("rent:approve_test:"))
async def admin_approve_as_test_drive(callback: CallbackQuery) -> None:
    if not is_admin_control_user(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    rental_id = int(callback.data.rsplit(":", 1)[1])
    current_rental = storage.get_by_id(rental_id)
    if current_rental is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not is_rental_waiting_approval(current_rental):
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return
    rental = storage.approve_waiting_as_test_drive(rental_id)
    if rental is None:
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return
    sent_to_work_chat = await publish_rental_to_work_chat(callback.message.bot, rental)
    await callback.message.edit_text(
        f"Заявка #{rental.rental_no or rental.id} одобрена как тест-драйв"
        f"{' и отправлена в рабочий чат' if sent_to_work_chat else ', но не отправлена в рабочий чат'}.\n"
        f"{rental.employee_name or 'Без ФИО'}: {rental.model} {rental.plate}\n"
        "Сумма: 0 руб."
    )
    await callback.answer("Одобрено как тест-драйв")


@dp.callback_query(F.data.startswith("rent:approve_amount:"))
async def admin_approve_amount_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin_control_user(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    rental_id = int(callback.data.rsplit(":", 1)[1])
    rental = storage.get_by_id(rental_id)
    if rental is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not is_rental_waiting_approval(rental):
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return
    await state.update_data(admin_rental_id=rental_id)
    await state.set_state(AdminAmountFlow.amount)
    await callback.message.answer(
        f"Введите сумму аренды для заявки #{rental.rental_no or rental.id} одним числом, например: 1700"
    )
    await callback.answer()


@dp.message(AdminAmountFlow.amount)
async def admin_set_amount_finish(message: Message, state: FSMContext) -> None:
    if (username(message) or "") not in admin_control_usernames():
        await message.answer("Недостаточно прав.")
        await state.clear()
        return
    raw_amount = (message.text or "").strip().replace(" ", "")
    if not raw_amount.isdigit():
        await message.answer("Введите сумму одним числом, например: 1700")
        return
    data = await state.get_data()
    rental_id = int(data["admin_rental_id"])
    current_rental = storage.get_by_id(rental_id)
    if current_rental is None:
        await message.answer("Заявка не найдена.")
        await state.clear()
        return
    if not is_rental_waiting_approval(current_rental):
        await message.answer("Эта заявка уже обработана. Повторно отправлять ее в рабочий чат не буду.")
        await state.clear()
        return
    rental = storage.approve_waiting_with_total(rental_id, int(raw_amount), approval_status="approved_manual")
    await state.clear()
    if rental is None:
        await message.answer("Эта заявка уже обработана. Повторно отправлять ее в рабочий чат не буду.")
        return
    sent_to_work_chat = await publish_rental_to_work_chat(message.bot, rental)
    await message.answer(
        f"Заявка #{rental.rental_no or rental.id} одобрена, сумма изменена на {rental.total or 0} руб. "
        + ("Заявка отправлена в рабочий чат." if sent_to_work_chat else "Заявка не отправлена в рабочий чат, проверьте настройки и логи бота.")
    )


@dp.callback_query(F.data.startswith("rent:reject:"))
async def admin_reject_rental(callback: CallbackQuery) -> None:
    if not is_admin_control_user(callback):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    rental_id = int(callback.data.rsplit(":", 1)[1])
    current_rental = storage.get_by_id(rental_id)
    if current_rental is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not is_rental_waiting_approval(current_rental):
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return
    rental = storage.set_approval_status(rental_id, "rejected")
    if rental is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    employee_notified = True
    try:
        await callback.message.bot.send_message(
            chat_id=rental.user_id,
            text=(
                f"Заявка #{rental.rental_no or rental.id} пока не одобрена.\n"
                "Свяжитесь с @Fedos_AV в личные сообщения. После согласования нажмите кнопку ниже."
            ),
            reply_markup=employee_reapproval_controls(rental.id),
        )
    except Exception:
        employee_notified = False
        logger.exception("Failed to notify employee about rejected rental %s", rental.id)
    await callback.message.edit_text(
        f"Заявка #{rental.rental_no or rental.id} не одобрена.\n"
        f"{rental.employee_name or 'Без ФИО'}: {rental.model} {rental.plate}\n"
        + (
            "Сотруднику отправлено сообщение."
            if employee_notified
            else "Не смог написать сотруднику в ЛС. Возможно, он не запускал бота."
        )
    )
    await callback.answer("Отказано")


@dp.callback_query(F.data.startswith("rent:resubmit:"))
async def employee_resubmit_rental(callback: CallbackQuery) -> None:
    rental_id = int(callback.data.rsplit(":", 1)[1])
    rental = storage.get_by_id(rental_id)
    if rental is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if callback.from_user.id != rental.user_id:
        await callback.answer("Это кнопка другого сотрудника", show_alert=True)
        return
    if rental.approval_status != "rejected":
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return
    rental = storage.set_approval_status(rental_id, "resubmitted")
    if rental is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    admin_sent = await send_admin_approval_request(
        callback.message.bot,
        rental,
        note="Сотрудник написал, что связался и согласовал. Проверьте заявку повторно.",
    )
    await callback.message.edit_text(
        "Заявка повторно отправлена на согласование."
        if admin_sent
        else "Заявка сохранена, но админ еще не запускал бота в личке. Напишите @Fedos_AV напрямую."
    )
    await callback.answer("Отправлено")


@dp.callback_query(F.data.startswith("rent:employee_cancel:"))
async def employee_cancel_rental(callback: CallbackQuery) -> None:
    rental_id = int(callback.data.rsplit(":", 1)[1])
    rental = storage.get_by_id(rental_id)
    if rental is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if callback.from_user.id != rental.user_id:
        await callback.answer("Это кнопка другого сотрудника", show_alert=True)
        return
    if rental.approval_status != "rejected":
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return
    storage.set_approval_status(rental_id, "employee_cancelled")
    await callback.message.edit_text(
        f"Заявка #{rental.rental_no or rental.id} отменена. В рабочий чат она не отправлялась."
    )
    await callback.answer("Отменено")


@dp.callback_query(F.data == "car:take")
async def start_take(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    started_at = now_moscow().isoformat(timespec="seconds")
    if not has_employee_name(callback.from_user):
        await state.update_data(pending_action="take", started_at=started_at)
        await state.set_state(ProfileFlow.name)
        await callback.message.answer("Введите ваше ФИО один раз, чтобы бот корректно формировал отчеты.")
        await callback.answer()
        return
    await state.update_data(started_at=started_at)
    await state.set_state(TakeFlow.model)
    await callback.message.answer(f"Выберите марку авто:\n\n{model_legend()}", reply_markup=model_menu())
    await callback.answer()


@dp.message(ProfileFlow.name)
async def save_profile_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        await message.answer("Не могу сохранить ФИО без Telegram-пользователя. Напишите боту обычным аккаунтом.")
        await state.clear()
        return
    full_name = " ".join((message.text or "").split())
    if len(full_name.split()) < 2:
        await message.answer("Пожалуйста, укажите ФИО полностью, например: Иванов Иван Иванович.")
        return
    storage.set_employee_name(message.from_user.id, full_name)
    data = await state.get_data()
    if data.get("pending_action") == "take":
        await state.set_state(TakeFlow.model)
        await message.answer("Спасибо, ФИО сохранено.\nВыберите марку авто:", reply_markup=model_menu())
        return
    if data.get("pending_action") == "test_drive":
        await state.set_state(TestDriveFlow.model)
        await message.answer("Спасибо, ФИО сохранено.\nВыберите марку авто для тест драйва:", reply_markup=model_menu("test_model"))
        return
    await state.clear()
    await message.answer("Спасибо, ФИО сохранено. Нажмите /start для продолжения.")


@dp.callback_query(TakeFlow.model, F.data.startswith("take_model:"))
async def take_model_button(callback: CallbackQuery, state: FSMContext) -> None:
    raw_index = callback.data.split(":", 1)[1]
    model = model_by_index(int(raw_index)) if raw_index.isdigit() else None
    if model is None:
        await callback.answer("Не нашел модель", show_alert=True)
        return
    await state.update_data(model=model)
    await state.set_state(TakeFlow.plate)
    await callback.message.answer(f"Выбрано: {model}\nВведите госномер, например: Н537РА126")
    await callback.answer()


@dp.callback_query(F.data.startswith("noop:"))
async def noop_callback(callback: CallbackQuery) -> None:
    await callback.answer()


@dp.message(TakeFlow.model)
async def take_model(message: Message, state: FSMContext) -> None:
    await message.answer("Выберите марку авто кнопкой из списка выше.")


@dp.message(TakeFlow.plate)
async def take_plate(message: Message, state: FSMContext) -> None:
    plate = normalize_plate(message.text or "")
    if not is_valid_plate(plate):
        await message.answer("Не понял госномер. Введите только номер, например: Н537РА126")
        return
    await state.update_data(plate=plate)
    await state.set_state(TakeFlow.return_text)
    await message.answer("Когда возврат? Например: завтра 18:30, 29 августа 20:00, 29.08.2026 12:00.")


@dp.message(TakeFlow.return_text)
async def take_return_text(message: Message, state: FSMContext) -> None:
    plan = parse_return_plan(message.text or "", now=now_moscow())
    if plan is None:
        await message.answer("Не понял дату возврата. Напишите, например: завтра 18:30, 29 августа 20:00 или 29.08.2026 12:00.")
        return
    await state.update_data(
        return_text=plan.text,
        planned_return_at=plan.planned_at.isoformat(timespec="minutes"),
        days=plan.days,
    )
    await state.set_state(TakeFlow.comment)
    await message.answer(
        f"Посчитал срок аренды: {plan.days} дн.\n"
        "Комментарий при взятии необязателен. Если согласовали, напишите с кем. Можно также указать цель, ночную смену или пропустить.",
        reply_markup=skip_take_comment_menu(),
    )


@dp.message(TakeFlow.comment)
async def take_comment(message: Message, state: FSMContext) -> None:
    await state.update_data(
        take_comment=(message.text or "").strip(),
        photo_count=0,
        first_photo_message_id=None,
        photo_message_ids=[],
        photo_file_ids=[],
    )
    await state.set_state(TakeFlow.photos)
    await message.answer(
        "Пришлите 5 фото: 4 стороны авто и 1 фото приборной панели, где виден уровень топлива."
    )


@dp.callback_query(TakeFlow.comment, F.data == "take:skip_comment")
async def skip_take_comment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(take_comment="", photo_count=0, first_photo_message_id=None, photo_message_ids=[], photo_file_ids=[])
    await state.set_state(TakeFlow.photos)
    await callback.message.answer(
        "Ок, без комментария. Пришлите 5 фото: 4 стороны авто и 1 фото приборной панели, где виден уровень топлива."
    )
    await callback.answer()


@dp.message(TakeFlow.photos, F.photo)
async def take_photos(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    count = int(data.get("photo_count", 0)) + 1
    first_photo_message_id = data.get("first_photo_message_id") or message.message_id
    photo_message_ids = list(data.get("photo_message_ids", []))
    photo_message_ids.append(message.message_id)
    file_ids = list(data.get("photo_file_ids", []))
    file_ids.append(message.photo[-1].file_id)
    await state.update_data(
        photo_count=count,
        first_photo_message_id=first_photo_message_id,
        photo_message_ids=photo_message_ids,
        photo_file_ids=file_ids,
    )

    if count < 5:
        await message.answer(f"Фото принято: {count}/5.")
        return

    data = await state.get_data()
    fake_text = (
        f"Взял {data['model']} {data['plate']} на {data['days']} дня, "
        f"{data.get('take_comment', '')}, возврат {data['return_text']}"
    )
    take = parse_take(fake_text)
    if take is None:
        await message.answer("Не смог собрать заявку. Начните заново через /car.")
        await state.clear()
        return
    if message.from_user is None:
        await message.answer("Не могу оформить выдачу без Telegram-пользователя. Напишите боту обычным аккаунтом.")
        await state.clear()
        return

    check = check_take_rules(config, take, username(message))
    started_at = data.get("started_at")
    rate, total = rental_price(take.model, take.days, data.get("planned_return_at"), started_at)
    rental_id = storage.create_take(
        chat_id=message.chat.id,
        message_id=first_photo_message_id,
        user_id=message.from_user.id,
        username=username(message),
        employee_name=employee_name(message),
        model=take.model,
        plate=take.plate,
        days=take.days,
        return_text=take.return_text,
        planned_return_at=data.get("planned_return_at"),
        night_shift=take.is_night_shift,
        photo_count=count,
        take_comment=data.get("take_comment"),
        rate=rate,
        total=total,
        created_at=started_at,
    )
    rental = storage.get_by_id(rental_id)
    storage.set_rental_photo_file_ids(rental_id, list(data.get("photo_file_ids", [])))
    public_no = rental.rental_no if rental and rental.rental_no else rental_id
    notes = [f"Заявка на выдачу #{public_no} зафиксирована: {take.model} {take.plate}, {take.days} дн., сумма {total} руб."]
    if check.warnings:
        notes.extend(check.warnings)
    if rental:
        admin_sent = await send_admin_approval_request(message.bot, rental)
        notes.append(
            "Заявка отправлена на согласование."
            if admin_sent
            else "Заявка сохранена, но админ еще не запускал бота в личке. Напишите ответственному."
        )
    summary = await message.answer("\n".join(notes))
    storage.update_take_message_id(rental_id, summary.message_id)
    await state.clear()


@dp.message(TakeFlow.photos)
async def take_photos_wrong(message: Message) -> None:
    await message.answer("На этом шаге нужны именно фото: 4 стороны авто и приборная панель с топливом.")


@dp.callback_query(F.data == "car:return")
async def start_return(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    rentals = storage.active_for_user(callback.message.chat.id, callback.from_user.id)
    if len(rentals) == 1:
        await state.update_data(plate=rentals[0].plate)
        await state.set_state(ReturnFlow.condition)
        await callback.message.answer(
            f"Сдаем {rentals[0].model} {rentals[0].plate}. Опишите недостатки машины или нажмите кнопку:",
            reply_markup=condition_menu(),
        )
    else:
        await state.set_state(ReturnFlow.plate)
        await callback.message.answer("Введите госномер машины, которую сдаете.")
    await callback.answer()


@dp.callback_query(F.data == "car:test_drive")
async def start_test_drive(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    started_at = now_moscow().isoformat(timespec="seconds")
    if not has_employee_name(callback.from_user):
        await state.update_data(pending_action="test_drive", started_at=started_at)
        await state.set_state(ProfileFlow.name)
        await callback.message.answer("Введите ваше ФИО один раз, чтобы бот корректно формировал отчеты.")
        await callback.answer()
        return
    await state.update_data(started_at=started_at)
    await state.set_state(TestDriveFlow.model)
    await callback.message.answer(f"Выберите марку авто для тест драйва:\n\n{model_legend()}", reply_markup=model_menu("test_model"))
    await callback.answer()


@dp.callback_query(TestDriveFlow.model, F.data.startswith("test_model:"))
async def test_drive_model_button(callback: CallbackQuery, state: FSMContext) -> None:
    raw_index = callback.data.split(":", 1)[1]
    model = model_by_index(int(raw_index)) if raw_index.isdigit() else None
    if model is None:
        await callback.answer("Не нашел модель", show_alert=True)
        return
    await state.update_data(model=model)
    await state.set_state(TestDriveFlow.plate)
    await callback.message.answer(f"Выбрано: {model}\nВведите госномер, например: Н537РА126")
    await callback.answer()


@dp.message(TestDriveFlow.model)
async def test_drive_model(message: Message, state: FSMContext) -> None:
    await message.answer("Выберите марку авто кнопкой из списка выше.")


@dp.message(TestDriveFlow.plate)
async def test_drive_plate(message: Message, state: FSMContext) -> None:
    plate = normalize_plate(message.text or "")
    if not is_valid_plate(plate):
        await message.answer("Не понял госномер. Введите только номер, например: Н537РА126")
        return
    await state.update_data(plate=plate)
    await state.set_state(TestDriveFlow.comment)
    await message.answer("Напишите, с кем согласован тест драйв. Это обязательный комментарий.")


@dp.message(TestDriveFlow.comment)
async def test_drive_comment(message: Message, state: FSMContext) -> None:
    comment = (message.text or "").strip()
    if not comment:
        await message.answer("Для тест драйва обязательно нужно указать, с кем он согласован.")
        return
    await state.update_data(
        test_comment=comment,
        photo_count=0,
        first_photo_message_id=None,
        photo_message_ids=[],
        photo_file_ids=[],
    )
    await state.set_state(TestDriveFlow.photos)
    await message.answer("Комментарий принят. Пришлите 5 фото: 4 стороны авто и приборная панель с уровнем топлива.")


@dp.message(TestDriveFlow.photos, F.photo)
async def test_drive_photos(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    count = int(data.get("photo_count", 0)) + 1
    first_photo_message_id = data.get("first_photo_message_id") or message.message_id
    photo_message_ids = list(data.get("photo_message_ids", []))
    photo_message_ids.append(message.message_id)
    file_ids = list(data.get("photo_file_ids", []))
    file_ids.append(message.photo[-1].file_id)
    await state.update_data(
        photo_count=count,
        first_photo_message_id=first_photo_message_id,
        photo_message_ids=photo_message_ids,
        photo_file_ids=file_ids,
    )
    if count < 5:
        await message.answer(f"Фото принято: {count}/5.")
        return
    if message.from_user is None:
        await message.answer("Не могу оформить тест драйв без Telegram-пользователя. Напишите боту обычным аккаунтом.")
        await state.clear()
        return

    data = await state.get_data()
    rental_id = storage.create_test_drive(
        chat_id=message.chat.id,
        message_id=first_photo_message_id,
        user_id=message.from_user.id,
        username=username(message),
        employee_name=employee_name(message),
        model=data["model"],
        plate=data["plate"],
        photo_count=count,
        comment=data["test_comment"],
        created_at=data.get("started_at"),
    )
    rental = storage.get_by_id(rental_id)
    storage.set_rental_photo_file_ids(rental_id, list(data.get("photo_file_ids", [])))
    public_no = rental.rental_no if rental and rental.rental_no else rental_id
    notes = [f"Тест драйв #{public_no} зафиксирован: {data['model']} {data['plate']}, бесплатно."]
    if rental:
        admin_sent = await send_admin_approval_request(message.bot, rental)
        notes.append(
            "Заявка отправлена на согласование."
            if admin_sent
            else "Заявка сохранена, но админ еще не запускал бота в личке. Напишите ответственному."
        )
    await message.answer("\n".join(notes))
    await state.clear()


@dp.message(TestDriveFlow.photos)
async def test_drive_photos_wrong(message: Message) -> None:
    await message.answer("На этом шаге нужны 5 фото: 4 стороны авто и приборная панель с топливом.")


@dp.message(ReturnFlow.plate)
async def return_plate(message: Message, state: FSMContext) -> None:
    plate = normalize_plate(message.text or "")
    if not is_valid_plate(plate):
        await message.answer("Не понял госномер. Введите только номер, например: Н537РА126")
        return
    block_message = return_plate_block_message(plate, storage.rentals_by_plate(plate))
    if block_message:
        await message.answer(block_message)
        return
    await state.update_data(plate=plate)
    await state.set_state(ReturnFlow.condition)
    await message.answer("Опишите недостатки машины или нажмите кнопку:", reply_markup=condition_menu())


@dp.callback_query(ReturnFlow.condition, F.data == "return:ok")
async def return_condition_ok(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        return_comment="Машина полностью исправна",
        condition_status="ok",
        photo_count=0,
        photo_message_ids=[],
        photo_file_ids=[],
    )
    await state.set_state(ReturnFlow.photos)
    await callback.message.answer("Пришлите 5 фото: 4 стороны авто и приборная панель с уровнем топлива.")
    await callback.answer()


@dp.message(ReturnFlow.condition)
async def return_condition_comment(message: Message, state: FSMContext) -> None:
    comment = (message.text or "").strip()
    if not comment:
        await message.answer("Нужен комментарий о недостатках или кнопка `Машина полностью исправна`.")
        return
    await state.update_data(return_comment=comment, condition_status="comment", photo_count=0, photo_message_ids=[], photo_file_ids=[])
    await state.set_state(ReturnFlow.photos)
    await message.answer("Комментарий принят. Теперь пришлите 5 фото: 4 стороны авто и приборная панель с уровнем топлива.")


@dp.message(ReturnFlow.photos, F.photo)
async def return_photos(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    count = int(data.get("photo_count", 0)) + 1
    first_photo_message_id = data.get("first_photo_message_id") or message.message_id
    photo_message_ids = list(data.get("photo_message_ids", []))
    photo_message_ids.append(message.message_id)
    file_ids = list(data.get("photo_file_ids", []))
    file_ids.append(message.photo[-1].file_id)
    await state.update_data(
        photo_count=count,
        first_photo_message_id=first_photo_message_id,
        photo_message_ids=photo_message_ids,
        photo_file_ids=file_ids,
    )
    if count < 5:
        await message.answer(f"Фото принято: {count}/5.")
        return

    data = await state.get_data()
    return_user_id = message.from_user.id if message.from_user else None
    return_username = username(message)
    return_employee_name = employee_name(message)
    candidate = storage.find_return_candidate(data["plate"], return_user_id)
    if candidate is None:
        await message.answer("Не нашел активную выдачу по этому номеру. Проверьте номер или обратитесь к ответственному.")
        await state.clear()
        return
    preview = return_preview_rental(
        candidate,
        first_photo_message_id,
        data["plate"],
        data.get("return_comment"),
        data.get("condition_status"),
        return_user_id,
        return_username,
        return_employee_name,
    )
    sent_messages = await send_to_work_chat(
        message.bot,
        list(data.get("photo_file_ids", [])),
        format_return_application(preview, comment=data.get("return_comment")),
    )
    if not sent_messages:
        await message.answer(work_chat_delivery_text(sent_messages) + "\nВозврат не зафиксирован. Попробуйте позже через /car.")
        await state.clear()
        return
    rental = storage.mark_returned(
        message.chat.id,
        first_photo_message_id,
        data["plate"],
        count,
        return_comment=data.get("return_comment"),
        condition_status=data.get("condition_status"),
        user_id=return_user_id,
        username=return_username,
        employee_name=return_employee_name,
    )
    if rental is None:
        await message.answer("Фото отправлены в рабочий чат, но выдача уже изменилась. Обратитесь к ответственному.")
        await state.clear()
        return
    notes = [f"Возврат зафиксирован: {rental.model} {rental.plate}, сумма {rental.total or 0} руб."]
    notes.append(work_chat_delivery_text(sent_messages))
    storage.update_return_work_message(
        rental.id,
        sent_messages[0].chat.id,
        sent_messages[0].message_id,
        [sent.message_id for sent in sent_messages],
    )
    rental = storage.get_by_id(rental.id) or rental
    await send_return_plate_correction_control(message.bot, rental)
    if rental.total and rental.total > 0:
        notes.append("После списания аренды ответственный отправляет /paid ответом на это сообщение.")
    summary = await message.answer("\n".join(notes))
    storage.update_return_message_id(rental.id, summary.message_id)
    await state.clear()


@dp.message(ReturnFlow.photos)
async def return_photos_wrong(message: Message) -> None:
    await message.answer("На этом шаге нужны 5 фото: 4 стороны авто и приборная панель с топливом.")


@dp.callback_query(F.data.startswith("return:change_plate:"))
async def return_change_plate_start(callback: CallbackQuery, state: FSMContext) -> None:
    rental_id = int(callback.data.rsplit(":", 1)[1])
    rental = storage.get_by_id(rental_id)
    if rental is None:
        await callback.answer("Сдача не найдена", show_alert=True)
        return
    if rental.return_user_id != callback.from_user.id:
        await callback.answer("Изменить номер может только сотрудник, который провел эту сдачу.", show_alert=True)
        return
    await state.update_data(
        correction_rental_id=rental_id,
        correction_control_chat_id=callback.message.chat.id,
        correction_control_message_id=callback.message.message_id,
    )
    await state.set_state(ReturnPlateCorrectionFlow.plate)
    await callback.message.answer(
        f"Введите правильный госномер для сдачи #{rental.rental_no or rental.id}, например: Т339ВТ159"
    )
    await callback.answer()


@dp.message(ReturnPlateCorrectionFlow.plate)
async def return_change_plate_finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    rental_id = int(data["correction_rental_id"])
    rental = storage.get_by_id(rental_id)
    if rental is None:
        await message.answer("Сдача не найдена.")
        await state.clear()
        return
    if not message.from_user or rental.return_user_id != message.from_user.id:
        await message.answer("Изменить номер может только сотрудник, который провел эту сдачу.")
        await state.clear()
        return
    new_plate = normalize_plate(message.text or "")
    if not is_valid_plate(new_plate):
        await message.answer("Не понял номер. Введите госномер, например: Т339ВТ159")
        return
    rental = storage.update_return_plate(rental_id, new_plate)
    await state.clear()
    if rental is None:
        await message.answer("Сдача не найдена.")
        return

    updated_summary = format_return_application(rental)
    if rental.return_work_chat_id and rental.return_work_message_id:
        try:
            await message.bot.edit_message_caption(
                chat_id=rental.return_work_chat_id,
                message_id=rental.return_work_message_id,
                caption=updated_summary,
            )
        except Exception:
            try:
                await message.bot.edit_message_text(
                    chat_id=rental.return_work_chat_id,
                    message_id=rental.return_work_message_id,
                    text=updated_summary,
                )
            except Exception:
                logger.exception("Failed to edit return work message after plate correction for rental %s", rental.id)

    control_chat_id = data.get("correction_control_chat_id")
    control_message_id = data.get("correction_control_message_id")
    if control_chat_id and control_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=control_chat_id,
                message_id=control_message_id,
                text=f"Сдача #{rental.rental_no or rental.id}: госномер сдачи изменен на {rental.return_plate or rental.plate}.",
            )
        except Exception:
            logger.exception("Failed to edit return plate correction control for rental %s", rental.id)
    await message.answer(
        f"Госномер в сдаче #{rental.rental_no or rental.id} изменен на {rental.return_plate or rental.plate}."
    )


@dp.message(F.reply_to_message)
async def approval_message(message: Message) -> None:
    approval = parse_approval(message.text or message.caption or "")
    if approval is None:
        await collect_or_process(message)
        return
    if not is_approver(message):
        await message.reply("Согласование может отправить только Сергей, администратор или @stax_ru.")
        return
    rental = storage.get_by_take_message(message.chat.id, message.reply_to_message.message_id)
    if rental is None:
        await message.reply("Не нашел выдачу в сообщении, на которое вы ответили.")
        return
    storage.set_approval(
        chat_id=message.chat.id,
        take_message_id=message.reply_to_message.message_id,
        approval_message_id=message.message_id,
        rate=approval.rate,
        total=approval.total,
        approval_status=approval.status,
    )
    take_from_reply = parse_take(message.reply_to_message.caption or message.reply_to_message.text or "")
    warnings = []
    if take_from_reply is not None:
        expected = check_take_rules(config, take_from_reply, rental.username)
        warnings = validate_approval(expected, approval)
    answer = ["Согласование зафиксировано."]
    answer.extend(warnings)
    await message.reply("\n".join(answer))


@dp.message()
async def collect_or_process(message: Message) -> None:
    if message.media_group_id:
        buffer = media_groups[message.media_group_id]
        buffer.messages.append(message)
        if buffer.task is None:
            buffer.task = asyncio.create_task(flush_media_group(message.media_group_id))
        return
    await process_messages([message])


async def notify_admins(bot: Bot, text: str) -> None:
    for admin_username in admin_control_usernames():
        admin_user_id = storage.get_setting(f"user_id:{admin_username}")
        if not admin_user_id:
            continue
        try:
            await bot.send_message(chat_id=int(admin_user_id), text=text)
        except Exception:
            logger.exception("Failed to notify admin %s", admin_username)


async def send_return_reminder(bot: Bot, rental) -> None:
    try:
        await bot.send_message(
            chat_id=rental.user_id,
            text=(
                f"Напоминание по выдаче #{rental.rental_no or rental.id}: "
                f"{rental.model} {rental.plate} нужно вернуть до {format_dt(rental.planned_return_at)}.\n"
                "Не забудьте поменять статус в САВ."
            ),
        )
    except Exception:
        logger.exception("Failed to send return reminder for rental %s", rental.id)


async def send_overdue_notice(bot: Bot, rental) -> None:
    text = (
        f"Просрочен возврат по выдаче #{rental.rental_no or rental.id}: "
        f"{rental.employee_name or 'Без ФИО'} "
        f"({'@' + rental.username if rental.username else 'id ' + str(rental.user_id)}) - "
        f"{rental.model} {rental.plate}, плановый возврат {format_dt(rental.planned_return_at)}.\n"
        "Не забудьте поменять статус в САВ."
    )
    try:
        await bot.send_message(chat_id=rental.user_id, text=text)
    except Exception:
        logger.exception("Failed to send overdue notice to employee for rental %s", rental.id)
    await notify_admins(bot, text)


async def notify_employee_auto_approved(bot: Bot, rental, sent_to_work_chat: bool) -> None:
    try:
        await bot.send_message(
            chat_id=rental.user_id,
            text=(
                f"Заявка #{rental.rental_no or rental.id} автоматически одобрена, так как 15 минут не было решения админа.\n"
                + (
                    "Заявка отправлена в рабочий чат."
                    if sent_to_work_chat
                    else "Но заявку не удалось отправить в рабочий чат, ответственный увидит ошибку в логах."
                )
            ),
        )
    except Exception:
        logger.exception("Failed to notify employee about auto approved rental %s", rental.id)


async def auto_approval_loop(bot: Bot) -> None:
    while True:
        try:
            cutoff = (now_moscow() - AUTO_APPROVAL_AFTER).isoformat(timespec="seconds")
            for waiting_rental in storage.pending_approval_older_than(cutoff):
                if is_test_drive_rental(waiting_rental):
                    rental = storage.approve_waiting_as_test_drive(waiting_rental.id)
                else:
                    rental = storage.approve_waiting(waiting_rental.id, "auto_approved")
                if rental is None:
                    continue
                sent_to_work_chat = await publish_rental_to_work_chat(bot, rental)
                await mark_admin_approval_messages_auto_approved(bot, rental, sent_to_work_chat)
                logger.info(
                    "Rental %s auto approved after %s minutes. sent_to_work_chat=%s",
                    rental.id,
                    int(AUTO_APPROVAL_AFTER.total_seconds() // 60),
                    sent_to_work_chat,
                )
                await notify_employee_auto_approved(bot, rental, sent_to_work_chat)
        except Exception:
            logger.exception("Auto approval loop failed")
        await asyncio.sleep(AUTO_APPROVAL_CHECK_INTERVAL_SECONDS)


async def return_control_loop(bot: Bot) -> None:
    while True:
        try:
            current = now_moscow()
            for rental in storage.active_rentals():
                if not rental.planned_return_at:
                    continue
                try:
                    planned = datetime.fromisoformat(rental.planned_return_at)
                except ValueError:
                    continue
                seconds_left = (planned - current).total_seconds()
                reminder_key = f"return_reminder_sent:{rental.id}"
                overdue_key = f"return_overdue_sent:{rental.id}"
                if 0 < seconds_left <= REMINDER_BEFORE_RETURN.total_seconds() and not storage.get_setting(reminder_key):
                    await send_return_reminder(bot, rental)
                    storage.set_setting(reminder_key, now_moscow().isoformat(timespec="seconds"))
                if seconds_left < 0 and not storage.get_setting(overdue_key):
                    await send_overdue_notice(bot, rental)
                    storage.set_setting(overdue_key, now_moscow().isoformat(timespec="seconds"))
        except Exception:
            logger.exception("Return control loop failed")
        await asyncio.sleep(REMINDER_CHECK_INTERVAL_SECONDS)


async def main() -> None:
    bot = Bot(token=config.bot_token)
    logger.info("Starting AC STAX bot. db_path=%s work_chat_id=%s", config.db_path, effective_work_chat_id())
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть меню"),
            BotCommand(command="help", description="Показать инструкцию"),
        ]
    )
    await bot.delete_webhook(drop_pending_updates=False)
    return_control_task = asyncio.create_task(return_control_loop(bot))
    auto_approval_task = asyncio.create_task(auto_approval_loop(bot))
    try:
        await dp.start_polling(bot, backoff_config=POLLING_BACKOFF)
    finally:
        logger.info("Stopping AC STAX bot")
        for task in (return_control_task, auto_approval_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
