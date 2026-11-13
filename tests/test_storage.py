from bot.storage import Storage


def test_storage_creates_database_directory(tmp_path):
    db_path = tmp_path / "nested" / "data" / "bot.sqlite3"
    Storage(str(db_path))

    assert db_path.exists()


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
        username="driver",
        employee_name="Иван Иванов",
    )

    assert rental is not None
    assert rental.id == rental_id
    assert rental.status == "returned"
    assert rental.return_user_id == 777
    assert rental.return_username == "driver"
    assert rental.return_employee_name == "Иван Иванов"


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
        username="manager",
        employee_name="Александр Михно",
    )

    assert rental is not None
    assert rental.id == rental_id
    assert rental.status == "returned"
    assert rental.return_user_id == 888
    assert rental.return_username == "manager"
    assert rental.return_employee_name == "Александр Михно"


def test_rentals_by_plate_normalizes_latin_lookalike_letters(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    rental_id = storage.create_take(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="driver",
        employee_name="Александр Михно",
        model="HYUNDAI SONATA",
        plate="В820НУ172",
        days=1,
        return_text="завтра",
        planned_return_at="2026-07-22T10:00",
        night_shift=False,
        photo_count=5,
        total=1700,
        created_at="2026-07-21T10:00:00",
    )

    rows = storage.rentals_by_plate("B820HY172")

    assert [row.id for row in rows] == [rental_id]


def test_find_return_candidate_does_not_close_rental(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    rental_id = storage.create_take(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="driver",
        employee_name="Александр Михно",
        model="HYUNDAI SONATA",
        plate="В820НУ172",
        days=1,
        return_text="завтра",
        planned_return_at="2026-07-22T10:00",
        night_shift=False,
        photo_count=5,
        total=1700,
        created_at="2026-07-21T10:00:00",
    )
    storage.set_approval_status(rental_id, "approved")

    candidate = storage.find_return_candidate("B820HY172", 777)
    rental = storage.get_by_id(rental_id)

    assert candidate is not None
    assert candidate.id == rental_id
    assert rental.status == "taken"
    assert rental.returned_at is None


def test_return_closes_current_employees_rental_when_plate_has_duplicates(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    armans_rental_id = storage.create_take(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="pagorodu",
        employee_name="Агаджанян Арман Андраникович",
        model="HYUNDAI SONATA",
        plate="А882СА761",
        days=1,
        return_text="завтра в 09:30",
        planned_return_at="2026-11-13T09:30:00",
        night_shift=True,
        photo_count=5,
        total=900,
        created_at="2026-11-12T18:30:00",
    )
    duplicate_id = storage.create_take(
        chat_id=222,
        message_id=3,
        user_id=888,
        username="other",
        employee_name="Другой сотрудник",
        model="HYUNDAI SONATA",
        plate="A882CA761",
        days=1,
        return_text="завтра",
        planned_return_at="2026-11-13T09:30:00",
        night_shift=True,
        photo_count=5,
        total=900,
        created_at="2026-11-12T19:00:00",
    )
    storage.set_approval_status(armans_rental_id, "approved")
    storage.set_approval_status(duplicate_id, "approved")

    candidate = storage.find_return_candidate("A882CA761", 777)
    returned = storage.mark_returned(
        chat_id=333,
        message_id=9,
        plate="А882СА761",
        photo_count=5,
        return_comment="Машина полностью исправна",
        condition_status="ok",
        user_id=777,
        username="pagorodu",
        employee_name="Агаджанян Арман Андраникович",
        rental_id=candidate.id if candidate else None,
    )

    assert candidate is not None
    assert returned is not None
    assert returned.id == armans_rental_id
    assert storage.get_by_id(armans_rental_id).status == "returned"
    assert storage.get_by_id(duplicate_id).status == "taken"


def test_restore_latest_returned_by_plate_reopens_rental(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    rental_id = storage.create_take(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="driver",
        employee_name="Александр Михно",
        model="HYUNDAI SONATA",
        plate="В820НУ172",
        days=1,
        return_text="завтра",
        planned_return_at="2026-07-22T10:00",
        night_shift=False,
        photo_count=5,
        total=1700,
        created_at="2026-07-21T10:00:00",
    )
    storage.set_approval_status(rental_id, "approved")
    storage.mark_returned(
        chat_id=222,
        message_id=9,
        plate="В820НУ172",
        photo_count=5,
        return_comment="Машина полностью исправна",
        condition_status="ok",
        user_id=888,
        username="manager",
        employee_name="Александр Михно",
    )

    rental = storage.restore_latest_returned_by_plate("B820HY172")

    assert rental is not None
    assert rental.id == rental_id
    assert rental.status == "taken"
    assert rental.returned_at is None
    assert rental.return_user_id is None
    assert rental.return_comment is None
    assert rental.return_plate is None
    assert rental.paid is False


def test_restore_latest_returned_by_plate_reopens_test_drive(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    rental_id = storage.create_test_drive(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="kicket22",
        employee_name="Михно Александр Васильевич",
        model="HYUNDAI SOLARIS",
        plate="В820НУ172",
        photo_count=5,
        comment="Согласовано: Александр Федосеев",
        created_at="2026-07-30T18:42:00",
    )
    storage.approve_waiting_as_test_drive(rental_id)
    with storage.connect() as conn:
        conn.execute(
            """
            UPDATE rentals
            SET status = 'returned', returned_at = created_at, paid = 1
            WHERE id = ?
            """,
            (rental_id,),
        )

    rental = storage.restore_latest_returned_by_plate("B820HY172")

    assert rental is not None
    assert rental.id == rental_id
    assert rental.status == "taken"
    assert rental.approval_status == "test_drive"
    assert rental.days == 0
    assert rental.total == 0
    assert rental.returned_at is None
    assert rental.paid is False


def test_create_test_drive_stays_active_until_return(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    rental_id = storage.create_test_drive(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="kicket22",
        employee_name="Михно Александр Васильевич",
        model="HYUNDAI SOLARIS",
        plate="В820НУ172",
        photo_count=5,
        comment="Согласовано: Александр Федосеев",
        created_at="2026-07-30T18:42:00",
    )

    rental = storage.get_by_id(rental_id)

    assert rental.status == "taken"
    assert rental.returned_at is None
    assert rental.return_user_id is None
    assert rental.return_username is None
    assert rental.return_employee_name is None
    assert rental.total == 0
    assert rental.days == 0


def test_approving_test_drive_keeps_it_active(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    rental_id = storage.create_test_drive(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="kicket22",
        employee_name="Михно Александр Васильевич",
        model="HYUNDAI SOLARIS",
        plate="В820НУ172",
        photo_count=5,
        comment="Согласовано: Александр Федосеев",
        created_at="2026-07-30T18:42:00",
    )

    rental = storage.approve_waiting_as_test_drive(rental_id)

    assert rental.status == "taken"
    assert rental.approval_status == "test_drive"
    assert rental.returned_at is None
    assert rental.total == 0
    assert rental.days == 0


def test_return_plate_can_be_corrected(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    rental_id = storage.create_take(
        chat_id=111,
        message_id=2,
        user_id=777,
        username="driver",
        employee_name="Иван Иванов",
        model="KIA K5",
        plate="Е899СМ761",
        days=1,
        return_text="завтра",
        planned_return_at="2026-07-22T10:00",
        night_shift=False,
        photo_count=5,
        total=1700,
        created_at="2026-07-21T10:00:00",
    )
    storage.set_approval_status(rental_id, "approved")
    storage.mark_returned(
        chat_id=222,
        message_id=9,
        plate="Е899СМ761",
        photo_count=5,
        return_comment="Машина полностью исправна",
        condition_status="ok",
        user_id=777,
        username="driver",
        employee_name="Иван Иванов",
    )

    rental = storage.update_return_plate(rental_id, "T339BT159")

    assert rental is not None
    assert rental.plate == "Е899СМ761"
    assert rental.return_plate == "Т339ВТ159"


def test_paid_can_be_marked_by_any_return_work_album_message(tmp_path):
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
    storage.mark_returned(
        chat_id=777,
        message_id=30,
        plate="Т339ВТ159",
        photo_count=5,
        return_comment="Машина полностью исправна",
        condition_status="ok",
        user_id=777,
        username="driver",
        employee_name="Иван Иванов",
    )
    storage.update_return_work_message(rental_id, chat_id=-100, message_id=501, message_ids=[501, 502, 503, 504, 505])

    assert storage.mark_paid_by_return_message(-100, 504) is True
    assert storage.get_by_id(rental_id).paid is True


def test_waiting_approval_can_be_approved_only_once(tmp_path):
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

    first = storage.approve_waiting(rental_id)
    second = storage.approve_waiting(rental_id)

    assert first is not None
    assert first.approval_status == "approved"
    assert second is None


def test_pending_approval_older_than_returns_only_waiting_old_rows(tmp_path):
    db_path = tmp_path / "bot.sqlite3"
    storage = Storage(str(db_path))
    old_id = storage.create_take(
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
    new_id = storage.create_take(
        chat_id=111,
        message_id=3,
        user_id=888,
        username="driver2",
        employee_name="Петр Петров",
        model="KIA K5",
        plate="А111АА777",
        days=1,
        return_text="завтра",
        planned_return_at="2026-07-22T10:00",
        night_shift=False,
        photo_count=5,
        total=1700,
        created_at="2026-07-21T10:20:00",
    )
    approved_id = storage.create_take(
        chat_id=111,
        message_id=4,
        user_id=999,
        username="driver3",
        employee_name="Сидор Сидоров",
        model="KIA K5",
        plate="В222ВВ777",
        days=1,
        return_text="завтра",
        planned_return_at="2026-07-22T10:00",
        night_shift=False,
        photo_count=5,
        total=1700,
        created_at="2026-07-21T10:00:00",
    )
    storage.set_approval_status(approved_id, "approved")

    rows = storage.pending_approval_older_than("2026-07-21T10:15:00")

    assert [row.id for row in rows] == [old_id]
    assert storage.approve_waiting(old_id, "auto_approved").approval_status == "auto_approved"
    assert storage.approve_waiting(old_id, "approved") is None
    assert storage.get_by_id(new_id).approval_status == "pending"
