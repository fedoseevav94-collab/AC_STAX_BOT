from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


CAR_MODELS: list[tuple[str, str, str]] = [
    ("КОМФОРТ +", "🟢", "EXEED LX"),
    ("КОМФОРТ +", "🟢", "Haval F7"),
    ("КОМФОРТ +", "🟢", "Belgee X70"),
    ("КОМФОРТ +", "🟢", "Chery Tiggo 7 Pro"),
    ("КОМФОРТ +", "🟢", "Kia K5"),
    ("КОМФОРТ +", "🟢", "Hyundai Sonata"),
    ("КОМФОРТ +", "🟢", "JAC J7"),
    ("КОМФОРТ", "🔵", "Chery Tiggo 4"),
    ("КОМФОРТ", "🔵", "Kia Optima"),
    ("КОМФОРТ", "🔵", "Hyundai Elantra"),
    ("ЭКОНОМ", "🟡", "Kia Rio"),
    ("ЭКОНОМ", "🟡", "Hyundai Solaris"),
]


def model_by_index(index: int) -> str | None:
    if 0 <= index < len(CAR_MODELS):
        return CAR_MODELS[index][2].upper()
    return None


def model_category(model: str) -> str | None:
    normalized = " ".join((model or "").upper().split())
    for category, _, car_model in CAR_MODELS:
        if normalized == car_model.upper():
            return category
    return None


def model_legend() -> str:
    return "🟢 КОМФОРТ +\n🔵 КОМФОРТ\n🟡 ЭКОНОМ"


def model_menu(callback_prefix: str = "take_model") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, (_, marker, model) in enumerate(CAR_MODELS):
        rows.append([InlineKeyboardButton(text=f"{marker} {model}", callback_data=f"{callback_prefix}:{index}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def car_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Взять машину", callback_data="car:take"),
                InlineKeyboardButton(text="Сдать машину", callback_data="car:return"),
            ],
            [InlineKeyboardButton(text="Тест драйв авто", callback_data="car:test_drive")],
        ]
    )


def start_menu(can_report: bool = False, can_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Взять машину", callback_data="car:take"),
            InlineKeyboardButton(text="Сдать машину", callback_data="car:return"),
        ],
        [InlineKeyboardButton(text="Тест драйв авто", callback_data="car:test_drive")],
    ]
    if can_report:
        rows.extend(
            [
                [InlineKeyboardButton(text="Месячный отчет", callback_data="report:month")],
                [InlineKeyboardButton(text="Отчет за прошлый месяц", callback_data="report:previous_month")],
                [InlineKeyboardButton(text="Список сотрудников", callback_data="report:employees")],
                [InlineKeyboardButton(text="Отчет по сотруднику", callback_data="report:employee_help")],
                [InlineKeyboardButton(text="Активные выдачи", callback_data="admin:active_rentals")],
            ]
        )
    if can_admin:
        rows.append([InlineKeyboardButton(text="Тарифы аренды", callback_data="admin:tariffs")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def condition_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Машина полностью исправна", callback_data="return:ok")],
        ]
    )


def skip_take_comment_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить комментарий", callback_data="take:skip_comment")],
        ]
    )


def admin_approval_controls(rental_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Одобрить без изменений", callback_data=f"rent:approve:{rental_id}")],
            [InlineKeyboardButton(text="Одобрить и изменить сумму", callback_data=f"rent:approve_amount:{rental_id}")],
            [InlineKeyboardButton(text="Одобрить как тест-драйв", callback_data=f"rent:approve_test:{rental_id}")],
            [InlineKeyboardButton(text="Не одобрено", callback_data=f"rent:reject:{rental_id}")],
        ]
    )


def employee_reapproval_controls(rental_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Связался и согласовал", callback_data=f"rent:resubmit:{rental_id}")],
            [InlineKeyboardButton(text="В выдаче отказано", callback_data=f"rent:employee_cancel:{rental_id}")],
        ]
    )


def tariff_controls() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Комфорт/Комфорт+ сутки", callback_data="tariff:set:comfort_day")],
            [InlineKeyboardButton(text="Комфорт/Комфорт+ 12 часов", callback_data="tariff:set:comfort_half")],
            [InlineKeyboardButton(text="Эконом сутки", callback_data="tariff:set:economy_day")],
            [InlineKeyboardButton(text="Эконом 12 часов", callback_data="tariff:set:economy_half")],
        ]
    )


def return_plate_correction_controls(rental_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить номер", callback_data=f"return:change_plate:{rental_id}")],
        ]
    )
