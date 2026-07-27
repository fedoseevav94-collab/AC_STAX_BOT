from bot.storage import Storage


def test_return_lookup_ignores_chat_and_normalizes_plate(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    rental_id = storage.create_take(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="driver",
        employee_name="Иван Иванов",
        model="KIA K5",
        plate="A111AA777",
        days=1,
        return_text="завтра",
        planned_return_at="2026-07-22T10:00",
        night_shift=False,
        photo_count=5,
        total=1700,
        created_at="2026-07-21T10:00:00",
    )
    storage.set_approval_status(rental_id, "approved")

    rental = storage.mark_returned(
        chat_id=222,
        message_id=9,
        plate="А111АА777",
        photo_count=5,
        return_comment="Машина полностью исправна",
        condition_status="ok",
        user_id=777,
    )

    assert rental is not None
    assert rental.id == rental_id
    assert rental.status == "returned"


def test_return_lookup_allows_another_employee_for_unique_plate(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    rental_id = storage.create_take(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="driver",
        employee_name="Иван Иванов",
        model="KIA K5",
        plate="Т339ВТ159",
        days=1,
        return_text="завтра",
        planned_return_at="2026-07-22T10:00",
        night_shift=False,
        photo_count=5,
        total=1700,
        created_at="2026-07-21T10:00:00",
    )
    storage.set_approval_status(rental_id, "approved")

    rental = storage.mark_returned(
        chat_id=222,
        message_id=9,
        plate="T339BT159",
        photo_count=5,
        return_comment="Машина полностью исправна",
        condition_status="ok",
        user_id=888,
    )

    assert rental is not None
    assert rental.id == rental_id
    assert rental.status == "returned"
