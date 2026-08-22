import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                deal_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                recipient TEXT,
                message TEXT,
                target_chat_id TEXT,
                image_id TEXT,
                max_message_id TEXT,
                status TEXT NOT NULL CHECK(status IN ('pending', 'accepted', 'rejected', 'error')),
                max_user_id TEXT,
                max_user_name TEXT,
                action TEXT,
                callback_claimed_at TEXT,
                bitrix_updated_at TEXT,
                comment_added_at TEXT,
                created_at TEXT NOT NULL,
                answered_at TEXT
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(requests)")}
        if "image_id" not in columns:
            connection.execute("ALTER TABLE requests ADD COLUMN image_id TEXT")
        for column in ("recipient", "message", "target_chat_id", "action", "callback_claimed_at", "bitrix_updated_at", "comment_added_at"):
            if column not in columns:
                connection.execute(f"ALTER TABLE requests ADD COLUMN {column} TEXT")


def create_request(
    request_id: str,
    deal_id: str,
    recipient_id: str,
    image_id: str | None = None,
    recipient: str | None = None,
    target_chat_id: str | None = None,
    message: str | None = None,
) -> None:
    with connect() as connection:
        connection.execute(
            "INSERT INTO requests (request_id, deal_id, recipient_id, recipient, message, target_chat_id, image_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (request_id, deal_id, recipient_id, recipient, message, target_chat_id or recipient_id, image_id, utc_now()),
        )


def latest_for_deal(deal_id: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM requests WHERE deal_id = ? ORDER BY id DESC LIMIT 1", (deal_id,)
        ).fetchone()


def mark_sent(request_id: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE requests SET status = 'pending' WHERE request_id = ?", (request_id,))


def set_message_id(request_id: str, message_id: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE requests SET max_message_id = ? WHERE request_id = ?", (message_id, request_id))


def set_error(request_id: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE requests SET status = 'error' WHERE request_id = ? AND status = 'pending'", (request_id,))


def set_status(request_id: str, status: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE requests SET status = ? WHERE request_id = ?", (status, request_id))


def claim_callback(request_id: str, action: str, user_id: str, user_name: str) -> tuple[str, sqlite3.Row | None]:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE requests
            SET callback_claimed_at = ?, action = ?, max_user_id = ?, max_user_name = ?
            WHERE request_id = ? AND status IN ('pending', 'error') AND callback_claimed_at IS NULL
            """,
            (utc_now(), action, user_id, user_name, request_id),
        )
        if cursor.rowcount != 1:
            existing = connection.execute("SELECT status FROM requests WHERE request_id = ?", (request_id,)).fetchone()
            return ("already_processed" if existing and existing["status"] in {"accepted", "rejected"} else "processing", None)
        return "claimed", connection.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,)).fetchone()


def complete_callback(request_id: str, status: str) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE requests SET status = ?, answered_at = ?, callback_claimed_at = NULL WHERE request_id = ?",
            (status, utc_now(), request_id),
        )


def release_callback(request_id: str) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE requests SET status = 'error', callback_claimed_at = NULL WHERE request_id = ?",
            (request_id,),
        )


def mark_bitrix_updated(request_id: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE requests SET bitrix_updated_at = ? WHERE request_id = ?", (utc_now(), request_id))


def mark_comment_added(request_id: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE requests SET comment_added_at = ? WHERE request_id = ?", (utc_now(), request_id))
