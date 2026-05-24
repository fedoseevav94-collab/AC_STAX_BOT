from datetime import datetime

from bot.dates import parse_return_plan
from bot.parser import parse_approval, parse_return, parse_take


def test_parse_take_regular():
    result = parse_take("Взял JAC J7 Н537РА126 на 2 дня, возврат 29 августа")
    assert result is not None
    assert result.model == "JAC J7"
    assert result.plate == "Н537РА126"
    assert result.days == 2
    assert result.return_text == "29 августа"
    assert result.is_night_shift is False


def test_parse_take_night_shift():
    result = parse_take("Взял JAC J7 Н537РА126 на 1 день, ночная смена, возврат завтра")
    assert result is not None
    assert result.is_night_shift is True
    assert result.return_text == "завтра"


def test_parse_return():
    result = parse_return("Вернул JAC J7 Н537РА126, аренда 2 дня")
    assert result is not None
    assert result.model == "JAC J7"
    assert result.plate == "Н537РА126"
    assert result.days == 2


def test_parse_short_return_with_comment():
    result = parse_return("Сдал с377ма797\nПри разгоне от 80 км/ч сильно трясет машину")
    assert result is not None
    assert result.model is None
    assert result.plate == "С377МА797"
    assert result.comment == "При разгоне от 80 км/ч сильно трясет машину"


def test_parse_paid_approval():
    result = parse_approval("Ставка - 1200, итого - 2400, статус: ожидает лицензию, подана 27 августа")
    assert result is not None
    assert result.is_free is False
    assert result.rate == 1200
    assert result.total == 2400
    assert result.status == "ожидает лицензию, подана 27 августа"


def test_parse_free_approval():
    result = parse_approval("Без оплаты аренды, авто в статусе СОВ")
    assert result is not None
    assert result.is_free is True
    assert result.status == "СОВ"


def test_parse_return_plan_tomorrow():
    result = parse_return_plan("завтра 18:30", now=datetime(2026, 5, 24, 12, 0))
    assert result is not None
    assert result.planned_at == datetime(2026, 5, 25, 18, 30)
    assert result.days == 1


def test_parse_return_plan_numeric_date():
    result = parse_return_plan("29.08.2026 12:00", now=datetime(2026, 5, 24, 12, 0))
    assert result is not None
    assert result.planned_at == datetime(2026, 8, 29, 12, 0)
