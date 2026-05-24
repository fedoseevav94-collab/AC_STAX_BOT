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


def model_legend() -> str:
    return "🟢 КОМФОРТ +\n🔵 КОМФОРТ\n🟡 ЭКОНОМ"


def model_menu() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, (_, marker, model) in enumerate(CAR_MODELS):
        rows.append([InlineKeyboardButton(text=f"{marker} {model}", callback_data=f"take_model:{index}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def car_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Взять машину", callback_data="car:take"),
                InlineKeyboardButton(text="Сдать машину", callback_data="car:return"),
            ]
        ]
    )


def start_menu(can_report: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Взять машину", callback_data="car:take"),
            InlineKeyboardButton(text="Сдать машину", callback_data="car:return"),
        ]
    ]
    if can_report:
        rows.extend(
            [
                [InlineKeyboardButton(text="Месячный отчет", callback_data="report:month")],
                [InlineKeyboardButton(text="Список сотрудников", callback_data="report:employees")],
                [InlineKeyboardButton(text="Отчет по сотруднику", callback_data="report:employee_help")],
            ]
        )
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
