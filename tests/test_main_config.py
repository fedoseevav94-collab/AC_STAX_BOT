from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


def load_main(monkeypatch, tmp_path, admin_usernames: str = ""):
    monkeypatch.setenv("BOT_TOKEN", "123456:test-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bot.sqlite3"))
    monkeypatch.setenv("ADMIN_USERNAMES", admin_usernames)
    sys.modules.pop("bot.main", None)
    import bot.main as main

    return importlib.reload(main)


def test_admin_usernames_from_env_get_full_admin_access(monkeypatch, tmp_path):
    main = load_main(monkeypatch, tmp_path, "LeylaUser")

    user = SimpleNamespace(username="LeylaUser")

    assert main.admin_control_usernames() == {"fedos_av", "leylauser"}
    assert main.is_admin_user_obj(user) is True


def test_overnight_comfort_rental_uses_half_day_rate(monkeypatch, tmp_path):
    main = load_main(monkeypatch, tmp_path)

    rate, total = main.rental_price("KIA K5", 1, "2026-07-31T09:30", "2026-07-30T18:40")

    assert rate == 900
    assert total == 900


def test_overnight_economy_rental_uses_half_day_rate(monkeypatch, tmp_path):
    main = load_main(monkeypatch, tmp_path)

    rate, total = main.rental_price("HYUNDAI SOLARIS", 1, "2026-07-31T09:30", "2026-07-30T18:40")

    assert rate == 600
    assert total == 600


def test_longer_than_night_window_uses_day_rate(monkeypatch, tmp_path):
    main = load_main(monkeypatch, tmp_path)

    rate, total = main.rental_price("KIA K5", 1, "2026-07-31T11:30", "2026-07-30T18:40")

    assert rate == 1700
    assert total == 1700


def test_auto_approval_admin_text_shows_processed_status(monkeypatch, tmp_path):
    main = load_main(monkeypatch, tmp_path)
    rental = SimpleNamespace(
        id=2,
        rental_no=2,
        employee_name="Михно Александр Васильевич",
        model="HYUNDAI SONATA",
        plate="А882СА761",
        days=1,
        condition_status=None,
        approval_status="auto_approved",
        total=900,
    )

    text = main.auto_approval_admin_text(rental, True)

    assert "одобрена автоматически через 15 минут" in text
    assert "Михно Александр Васильевич: HYUNDAI SONATA А882СА761" in text
    assert "Сумма: 900 руб." in text
    assert "Заявка отправлена в рабочий чат." in text
