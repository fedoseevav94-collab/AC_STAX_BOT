from __future__ import annotations

from dataclasses import dataclass

from bot.config import Config
from bot.parser import Approval, TakeRequest


@dataclass(frozen=True)
class RuleCheck:
    allowed: bool
    warnings: list[str]
    expected_rate: int | None
    expected_total: int | None


def check_take_rules(config: Config, request: TakeRequest, username: str | None) -> RuleCheck:
    warnings: list[str] = []
    username = (username or "").lower()
    free_count = config.free_models.get(request.model, 0)
    driver_rate = config.driver_rates.get(request.model)

    if driver_rate is None:
        warnings.append(f"Для модели {request.model} не задана водительская ставка.")
        return RuleCheck(False, warnings, None, None)

    if request.is_night_shift:
        return RuleCheck(True, warnings, 0, 0)

    if username in config.exempt_usernames:
        warnings.append("Пользователь в списке старых исключений. Если есть согласование, укажите его в комментарии.")
        return RuleCheck(True, warnings, None, None)

    if free_count > 10:
        rate = driver_rate // 2
        return RuleCheck(True, warnings, rate, rate * request.days)

    warnings.append("Свободных авто этой модели 10 или меньше: аренда допустима только по полной ставке.")
    return RuleCheck(True, warnings, driver_rate, driver_rate * request.days)


def validate_approval(expected: RuleCheck, approval: Approval) -> list[str]:
    warnings: list[str] = []
    if expected.expected_rate is not None and approval.rate is not None and approval.rate != expected.expected_rate:
        warnings.append(f"Ожидаемая ставка: {expected.expected_rate}, в согласовании указано: {approval.rate}.")
    if expected.expected_total is not None and approval.total is not None and approval.total != expected.expected_total:
        warnings.append(f"Ожидаемый итог: {expected.expected_total}, в согласовании указано: {approval.total}.")
    if expected.expected_total == 0 and not approval.is_free:
        warnings.append("Для ночной смены ожидалась выдача без оплаты аренды.")
    return warnings
