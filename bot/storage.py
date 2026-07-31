from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
LATIN_TO_CYRILLIC_PLATE = str.maketrans(
    {
        "A": "А",
        "B": "В",
        "E": "Е",
        "K": "К",
        "M": "М",
        "H": "Н",
        "O": "О",
        "P": "Р",
        "C": "С",
        "T": "Т",
        "Y": "У",
        "X": "Х",
    }
)


def now_moscow_iso() -> str:
    return datetime.now(MOSCOW_TZ).replace(tzinfo=None).isoformat(timespec="seconds")


def normalize_plate(plate: str) -> str:
    return re.sub(r"\s+", "", plate or "").upper().translate(LATIN_TO_CYRILLIC_PLATE)


@dataclass(frozen=True)
class Rental:
    id: int
    rental_no: int | None
    rental_month: str | None
    chat_id: int
    take_message_id: int
    return_message_id: int | None
    user_id: int
    username: str | None
    employee_name: str | None
    model: str
    plate: str
    return_plate: str | None
    days: int
    return_text: str | None
    planned_return_at: str | None
    take_comment: str | None
    return_comment: str | None
    condition_status: str | None
    status: str
    rate: int | None
    total: int | None
    paid: bool
    created_at: str
    returned_at: str | None
    approval_status: str | None
    return_user_id: int | None
    return_username: str | None
    return_employee_name: str | None
    return_work_chat_id: int | None
    return_work_message_id: int | None


class Storage:
    def __init__(self, path: str) -> None:
        self.path = path
        self._init()

    def connect(self) -> sqlite3.Connection:
        parent = Path(self.path).expanduser().parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rentals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rental_no INTEGER,
                    rental_month TEXT,
                    chat_id INTEGER NOT NULL,
                    take_message_id INTEGER NOT NULL,
                    return_message_id INTEGER,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    employee_name TEXT,
                    model TEXT NOT NULL,
                    plate TEXT NOT NULL,
                    return_plate TEXT,
                    days INTEGER NOT NULL,
                    return_text TEXT,
                    planned_return_at TEXT,
                    take_comment TEXT,
                    return_comment TEXT,
                    condition_status TEXT,
                    night_shift INTEGER NOT NULL DEFAULT 0,
                    photo_count_take INTEGER NOT NULL DEFAULT 0,
                    photo_count_return INTEGER NOT NULL DEFAULT 0,
                    approval_message_id INTEGER,
                    rate INTEGER,
                    total INTEGER,
                    approval_status TEXT,
                    status TEXT NOT NULL,
                    paid INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    returned_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rentals_plate_status ON rentals(plate, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rentals_take_message ON rentals(chat_id, take_message_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rentals_return_message ON rentals(chat_id, return_message_id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(conn)

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(rentals)").fetchall()}
        for name, ddl in {
            "take_comment": "ALTER TABLE rentals ADD COLUMN take_comment TEXT",
            "return_comment": "ALTER TABLE rentals ADD COLUMN return_comment TEXT",
            "condition_status": "ALTER TABLE rentals ADD COLUMN condition_status TEXT",
            "employee_name": "ALTER TABLE rentals ADD COLUMN employee_name TEXT",
            "planned_return_at": "ALTER TABLE rentals ADD COLUMN planned_return_at TEXT",
            "rental_no": "ALTER TABLE rentals ADD COLUMN rental_no INTEGER",
            "rental_month": "ALTER TABLE rentals ADD COLUMN rental_month TEXT",
            "return_user_id": "ALTER TABLE rentals ADD COLUMN return_user_id INTEGER",
            "return_username": "ALTER TABLE rentals ADD COLUMN return_username TEXT",
            "return_employee_name": "ALTER TABLE rentals ADD COLUMN return_employee_name TEXT",
            "return_work_chat_id": "ALTER TABLE rentals ADD COLUMN return_work_chat_id INTEGER",
            "return_work_message_id": "ALTER TABLE rentals ADD COLUMN return_work_message_id INTEGER",
            "return_plate": "ALTER TABLE rentals ADD COLUMN return_plate TEXT",
        }.items():
            if name not in existing:
                conn.execute(ddl)

    def create_take(
        self,
        chat_id: int,
        message_id: int,
        user_id: int,
        username: str | None,
        employee_name: str | None,
        model: str,
        plate: str,
        days: int,
        return_text: str,
        planned_return_at: str | None,
        night_shift: bool,
        photo_count: int,
        take_comment: str | None = None,
        rate: int | None = None,
        total: int | None = None,
        created_at: str | None = None,
    ) -> int:
        with self.connect() as conn:
            created_at = created_at or now_moscow_iso()
            rental_month = created_at[:7]
            row = conn.execute(
                "SELECT COALESCE(MAX(rental_no), 0) + 1 AS next_no FROM rentals WHERE rental_month = ?",
                (rental_month,),
            ).fetchone()
            rental_no = int(row["next_no"])
            cursor = conn.execute(
                """
                INSERT INTO rentals (
                    rental_no, rental_month, chat_id, take_message_id, user_id, username, employee_name, model, plate, days, return_text,
                    planned_return_at, night_shift, photo_count_take, take_comment, rate, total, approval_status, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'taken', ?)
                """,
                (
                    rental_no,
                    rental_month,
                    chat_id,
                    message_id,
                    user_id,
                    username,
                    employee_name,
                    model,
                    plate,
                    days,
                    return_text,
                    planned_return_at,
                    int(night_shift),
                    photo_count,
                    take_comment,
                    rate,
                    total,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def create_test_drive(
        self,
        chat_id: int,
        message_id: int,
        user_id: int,
        username: str | None,
        employee_name: str | None,
        model: str,
        plate: str,
        photo_count: int,
        comment: str,
        created_at: str | None = None,
    ) -> int:
        with self.connect() as conn:
            created_at = created_at or now_moscow_iso()
            rental_month = created_at[:7]
            row = conn.execute(
                "SELECT COALESCE(MAX(rental_no), 0) + 1 AS next_no FROM rentals WHERE rental_month = ?",
                (rental_month,),
            ).fetchone()
            rental_no = int(row["next_no"])
            cursor = conn.execute(
                """
                INSERT INTO rentals (
                    rental_no, rental_month, chat_id, take_message_id, return_message_id,
                    user_id, username, employee_name, model, plate, days, return_text,
                    planned_return_at, night_shift, photo_count_take, photo_count_return,
                    take_comment, return_comment, condition_status, rate, total, approval_status,
                    status, paid, created_at, returned_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', NULL, 0, ?, ?, ?, ?, 'test_drive', 0, 0, 'pending', 'returned', 1, ?, ?)
                """,
                (
                    rental_no,
                    rental_month,
                    chat_id,
                    message_id,
                    message_id,
                    user_id,
                    username,
                    employee_name,
                    model,
                    plate,
                    photo_count,
                    photo_count,
                    f"Тест драйв. Согласовано: {comment}",
                    comment,
                    created_at,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def set_approval(
        self,
        chat_id: int,
        take_message_id: int,
        approval_message_id: int,
        rate: int | None,
        total: int | None,
        approval_status: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE rentals
                SET approval_message_id = ?, rate = ?, total = ?, approval_status = ?
                WHERE chat_id = ? AND take_message_id = ?
                """,
                (approval_message_id, rate, total, approval_status, chat_id, take_message_id),
            )

    def update_take_message_id(self, rental_id: int, take_message_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE rentals SET take_message_id = ? WHERE id = ?", (take_message_id, rental_id))

    def update_return_message_id(self, rental_id: int, return_message_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE rentals SET return_message_id = ? WHERE id = ?", (return_message_id, rental_id))

    def mark_returned(
        self,
        chat_id: int,
        message_id: int,
        plate: str,
        photo_count: int,
        return_comment: str | None = None,
        condition_status: str | None = None,
        user_id: int | None = None,
        username: str | None = None,
        employee_name: str | None = None,
    ) -> Rental | None:
        with self.connect() as conn:
            params: list[int] = []
            user_filter = ""
            if user_id is not None:
                user_filter = "AND user_id = ?"
                params.append(user_id)
            rows = conn.execute(
                f"""
                SELECT * FROM rentals
                WHERE status = 'taken'
                    AND COALESCE(approval_status, 'approved') NOT IN ('pending', 'resubmitted', 'rejected', 'employee_cancelled')
                    {user_filter}
                ORDER BY id DESC
                """,
                params,
            ).fetchall()
            normalized_plate = normalize_plate(plate)
            row = next((candidate for candidate in rows if normalize_plate(candidate["plate"]) == normalized_plate), None)
            if row is None and user_id is not None:
                fallback_rows = conn.execute(
                    """
                    SELECT * FROM rentals
                    WHERE status = 'taken'
                        AND COALESCE(approval_status, 'approved') NOT IN ('pending', 'resubmitted', 'rejected', 'employee_cancelled')
                    ORDER BY id DESC
                    """
                ).fetchall()
                plate_matches = [
                    candidate for candidate in fallback_rows if normalize_plate(candidate["plate"]) == normalized_plate
                ]
                if len(plate_matches) == 1:
                    row = plate_matches[0]
            if row is None:
                return None
            conn.execute(
                """
                UPDATE rentals
                SET return_message_id = ?, return_plate = ?, photo_count_return = ?, return_comment = ?,
                    condition_status = ?, return_user_id = ?, return_username = ?,
                    return_employee_name = ?, status = 'returned', returned_at = ?
                WHERE id = ?
                """,
                (
                    message_id,
                    normalized_plate,
                    photo_count,
                    return_comment,
                    condition_status,
                    user_id,
                    username,
                    employee_name,
                    now_moscow_iso(),
                    row["id"],
                ),
            )
            conn.commit()
            return self.get_by_id(row["id"])

    def find_return_candidate(self, plate: str, user_id: int | None = None) -> Rental | None:
        with self.connect() as conn:
            params: list[int] = []
            user_filter = ""
            if user_id is not None:
                user_filter = "AND user_id = ?"
                params.append(user_id)
            rows = conn.execute(
                f"""
                SELECT * FROM rentals
                WHERE status = 'taken'
                    AND COALESCE(approval_status, 'approved') NOT IN ('pending', 'resubmitted', 'rejected', 'employee_cancelled')
                    {user_filter}
                ORDER BY id DESC
                """,
                params,
            ).fetchall()
            normalized_plate = normalize_plate(plate)
            row = next((candidate for candidate in rows if normalize_plate(candidate["plate"]) == normalized_plate), None)
            if row is None and user_id is not None:
                fallback_rows = conn.execute(
                    """
                    SELECT * FROM rentals
                    WHERE status = 'taken'
                        AND COALESCE(approval_status, 'approved') NOT IN ('pending', 'resubmitted', 'rejected', 'employee_cancelled')
                    ORDER BY id DESC
                    """
                ).fetchall()
                plate_matches = [
                    candidate for candidate in fallback_rows if normalize_plate(candidate["plate"]) == normalized_plate
                ]
                if len(plate_matches) == 1:
                    row = plate_matches[0]
            return _rental(row) if row is not None else None

    def update_return_work_message(
        self,
        rental_id: int,
        chat_id: int,
        message_id: int,
        message_ids: list[int] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE rentals
                SET return_work_chat_id = ?, return_work_message_id = ?
                WHERE id = ?
                """,
                (chat_id, message_id, rental_id),
            )
            if message_ids:
                conn.execute(
                    """
                    INSERT INTO settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (f"return_work_message_ids:{rental_id}", json.dumps(message_ids)),
                )

    def update_return_plate(self, rental_id: int, plate: str) -> Rental | None:
        with self.connect() as conn:
            conn.execute("UPDATE rentals SET return_plate = ? WHERE id = ?", (normalize_plate(plate), rental_id))
            conn.commit()
            return self.get_by_id(rental_id)

    def set_total(self, rental_id: int, total: int, approval_status: str = "manual") -> Rental | None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE rentals SET total = ?, approval_status = ? WHERE id = ?",
                (total, approval_status, rental_id),
            )
            conn.commit()
            return self.get_by_id(rental_id)

    def approve_waiting(self, rental_id: int, approval_status: str = "approved") -> Rental | None:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE rentals
                SET approval_status = ?
                WHERE id = ?
                    AND approval_status IN ('pending', 'resubmitted')
                """,
                (approval_status, rental_id),
            )
            conn.commit()
            return self.get_by_id(rental_id) if cursor.rowcount else None

    def approve_waiting_with_total(
        self,
        rental_id: int,
        total: int,
        approval_status: str = "approved_manual",
    ) -> Rental | None:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE rentals
                SET total = ?, approval_status = ?
                WHERE id = ?
                    AND approval_status IN ('pending', 'resubmitted')
                """,
                (total, approval_status, rental_id),
            )
            conn.commit()
            return self.get_by_id(rental_id) if cursor.rowcount else None

    def set_approval_status(self, rental_id: int, approval_status: str) -> Rental | None:
        with self.connect() as conn:
            conn.execute("UPDATE rentals SET approval_status = ? WHERE id = ?", (approval_status, rental_id))
            conn.commit()
            return self.get_by_id(rental_id)

    def approve_waiting_as_test_drive(self, rental_id: int) -> Rental | None:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE rentals
                SET days = 0, rate = 0, total = 0, condition_status = 'test_drive',
                    approval_status = 'test_drive', status = 'returned', paid = 1,
                    returned_at = COALESCE(returned_at, created_at)
                WHERE id = ?
                    AND approval_status IN ('pending', 'resubmitted')
                """,
                (rental_id,),
            )
            conn.commit()
            return self.get_by_id(rental_id) if cursor.rowcount else None

    def set_test_drive_status(self, rental_id: int, is_test_drive: bool, rate: int | None, total: int) -> Rental | None:
        with self.connect() as conn:
            if is_test_drive:
                conn.execute(
                    """
                    UPDATE rentals
                    SET days = 0, rate = 0, total = 0, condition_status = 'test_drive',
                        approval_status = 'test_drive', status = 'returned', paid = 1,
                        returned_at = COALESCE(returned_at, created_at)
                    WHERE id = ?
                    """,
                    (rental_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE rentals
                    SET days = CASE WHEN days <= 0 THEN 1 ELSE days END,
                        rate = ?, total = ?, condition_status = NULL,
                        approval_status = 'manual_rent', status = 'taken', paid = 0,
                        returned_at = NULL
                    WHERE id = ?
                    """,
                    (rate, total, rental_id),
                )
            conn.commit()
            return self.get_by_id(rental_id)

    def active_for_user(self, chat_id: int, user_id: int) -> list[Rental]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rentals
                WHERE user_id = ? AND status = 'taken'
                    AND COALESCE(approval_status, 'approved') NOT IN ('pending', 'resubmitted', 'rejected', 'employee_cancelled')
                ORDER BY id DESC
                """,
                (user_id,),
            ).fetchall()
            return [_rental(row) for row in rows]

    def active_rentals(self) -> list[Rental]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rentals
                WHERE status = 'taken'
                    AND COALESCE(approval_status, 'approved') NOT IN ('pending', 'resubmitted', 'rejected', 'employee_cancelled')
                ORDER BY planned_return_at IS NULL, planned_return_at, created_at
                """
            ).fetchall()
            return [_rental(row) for row in rows]

    def rentals_by_plate(self, plate: str) -> list[Rental]:
        normalized_plate = normalize_plate(plate)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rentals
                ORDER BY id DESC
                """
            ).fetchall()
            return [_rental(row) for row in rows if normalize_plate(row["plate"]) == normalized_plate]

    def pending_approval_older_than(self, cutoff_iso: str) -> list[Rental]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rentals
                WHERE approval_status IN ('pending', 'resubmitted')
                    AND created_at <= ?
                ORDER BY created_at, id
                """,
                (cutoff_iso,),
            ).fetchall()
            return [_rental(row) for row in rows]

    def monthly_report_rows(self, year_month: str, employee_query: str | None = None) -> list[sqlite3.Row]:
        with self.connect() as conn:
            params: list[str] = [year_month]
            employee_filter = ""
            if employee_query:
                query = employee_query.strip().lstrip("@").lower()
                employee_filter = """
                    AND (
                        lower(coalesce(username, '')) = ?
                        OR CAST(user_id AS TEXT) = ?
                        OR lower(coalesce(employee_name, '')) LIKE ?
                    )
                """
                params.extend([query, query, f"%{query}%"])
            return conn.execute(
                f"""
                SELECT
                    rental_no, rental_month, employee_name, username, user_id, model, plate, return_plate, days, return_text, planned_return_at,
                    take_comment, return_comment,
                    condition_status, rate, total, approval_status, paid, created_at, returned_at,
                    photo_count_take, photo_count_return
                FROM rentals
                WHERE substr(created_at, 1, 7) = ?
                    AND COALESCE(approval_status, 'approved') NOT IN ('pending', 'resubmitted', 'rejected', 'employee_cancelled')
                {employee_filter}
                ORDER BY lower(coalesce(employee_name, username, '')), days DESC, created_at
                """,
                params,
            ).fetchall()

    def employees_for_month(self, year_month: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT
                    employee_name,
                    username,
                    user_id,
                    COUNT(*) AS rentals_count,
                    SUM(days) AS total_days
                FROM rentals
                WHERE substr(created_at, 1, 7) = ?
                    AND COALESCE(approval_status, 'approved') NOT IN ('pending', 'resubmitted', 'rejected', 'employee_cancelled')
                GROUP BY user_id, username, employee_name
                ORDER BY lower(coalesce(employee_name, username, ''))
                """,
                (year_month,),
            ).fetchall()

    def set_employee_name(self, user_id: int, employee_name: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (f"employee_name:{user_id}", employee_name),
            )

    def get_employee_name(self, user_id: int) -> str | None:
        return self.get_setting(f"employee_name:{user_id}")

    def set_rental_photo_file_ids(self, rental_id: int, file_ids: list[str]) -> None:
        self.set_setting(f"rental_photo_file_ids:{rental_id}", json.dumps(file_ids, ensure_ascii=False))

    def get_rental_photo_file_ids(self, rental_id: int) -> list[str]:
        value = self.get_setting(f"rental_photo_file_ids:{rental_id}")
        if not value:
            return []
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(loaded, list):
            return []
        return [str(item) for item in loaded if item]

    def mark_paid_by_return_message(self, chat_id: int, return_message_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE rentals
                SET paid = 1
                WHERE (chat_id = ? AND return_message_id = ?)
                    OR (return_work_chat_id = ? AND return_work_message_id = ?)
                """,
                (chat_id, return_message_id, chat_id, return_message_id),
            )
            if cursor.rowcount > 0:
                return True
            rows = conn.execute(
                """
                SELECT rentals.id, settings.value
                FROM rentals
                JOIN settings ON settings.key = 'return_work_message_ids:' || rentals.id
                WHERE rentals.return_work_chat_id = ?
                """,
                (chat_id,),
            ).fetchall()
            for row in rows:
                try:
                    message_ids = json.loads(row["value"])
                except json.JSONDecodeError:
                    continue
                if return_message_id in {int(item) for item in message_ids}:
                    conn.execute("UPDATE rentals SET paid = 1 WHERE id = ?", (row["id"],))
                    return True
            return False

    def get_by_take_message(self, chat_id: int, message_id: int) -> Rental | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM rentals WHERE chat_id = ? AND take_message_id = ?",
                (chat_id, message_id),
            ).fetchone()
            return _rental(row) if row else None

    def get_by_id(self, rental_id: int) -> Rental | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM rentals WHERE id = ?", (rental_id,)).fetchone()
            return _rental(row) if row else None

    def active_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM rentals
                WHERE status = 'taken'
                    AND COALESCE(approval_status, 'approved') NOT IN ('pending', 'resubmitted', 'rejected', 'employee_cancelled')
                """
            ).fetchone()
            return int(row["count"])

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_setting(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None


def _rental(row: sqlite3.Row) -> Rental:
    return Rental(
        id=row["id"],
        rental_no=row["rental_no"],
        rental_month=row["rental_month"],
        chat_id=row["chat_id"],
        take_message_id=row["take_message_id"],
        return_message_id=row["return_message_id"],
        user_id=row["user_id"],
        username=row["username"],
        employee_name=row["employee_name"],
        model=row["model"],
        plate=row["plate"],
        return_plate=row["return_plate"],
        days=row["days"],
        planned_return_at=row["planned_return_at"],
        return_text=row["return_text"],
        take_comment=row["take_comment"],
        return_comment=row["return_comment"],
        condition_status=row["condition_status"],
        status=row["status"],
        rate=row["rate"],
        total=row["total"],
        paid=bool(row["paid"]),
        created_at=row["created_at"],
        returned_at=row["returned_at"],
        approval_status=row["approval_status"],
        return_user_id=row["return_user_id"],
        return_username=row["return_username"],
        return_employee_name=row["return_employee_name"],
        return_work_chat_id=row["return_work_chat_id"],
        return_work_message_id=row["return_work_message_id"],
    )
