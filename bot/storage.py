from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3


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


class Storage:
    def __init__(self, path: str) -> None:
        self.path = path
        self._init()

    def connect(self) -> sqlite3.Connection:
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
    ) -> int:
        with self.connect() as conn:
            created_at = datetime.now().isoformat(timespec="seconds")
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
                    planned_return_at, night_shift, photo_count_take, take_comment, rate, total, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'taken', ?)
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
    ) -> int:
        with self.connect() as conn:
            created_at = datetime.now().isoformat(timespec="seconds")
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
                    take_comment, return_comment, condition_status, rate, total,
                    status, paid, created_at, returned_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', NULL, 0, ?, ?, ?, ?, 'test_drive', 0, 0, 'returned', 1, ?, ?)
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
    ) -> Rental | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM rentals
                WHERE chat_id = ? AND plate = ? AND status = 'taken'
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id, plate),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE rentals
                SET return_message_id = ?, photo_count_return = ?, return_comment = ?,
                    condition_status = ?, status = 'returned', returned_at = ?
                WHERE id = ?
                """,
                (
                    message_id,
                    photo_count,
                    return_comment,
                    condition_status,
                    datetime.now().isoformat(timespec="seconds"),
                    row["id"],
                ),
            )
            return self.get_by_id(row["id"])

    def active_for_user(self, chat_id: int, user_id: int) -> list[Rental]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM rentals
                WHERE chat_id = ? AND user_id = ? AND status = 'taken'
                ORDER BY id DESC
                """,
                (chat_id, user_id),
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
                    rental_no, rental_month, employee_name, username, user_id, model, plate, days, return_text, planned_return_at,
                    take_comment, return_comment,
                    condition_status, rate, total, approval_status, paid, created_at, returned_at,
                    photo_count_take, photo_count_return
                FROM rentals
                WHERE substr(created_at, 1, 7) = ?
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

    def mark_paid_by_return_message(self, chat_id: int, return_message_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE rentals SET paid = 1 WHERE chat_id = ? AND return_message_id = ?",
                (chat_id, return_message_id),
            )
            return cursor.rowcount > 0

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
            row = conn.execute("SELECT COUNT(*) AS count FROM rentals WHERE status = 'taken'").fetchone()
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
    )
