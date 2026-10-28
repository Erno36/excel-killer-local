"""
auth/repository.py — CRUD de usuarios e intentos de login en SQLite.

Capa de acceso a datos pura; no contiene logica de negocio.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from data.models import LoginAttempt, User


class UserRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def find_by_username(self, username: str) -> User | None:
        row = self._conn.execute(
            "SELECT id, username, password_hash, is_active, is_test, created_at, updated_at "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return User(
            id=row["id"],
            username=row["username"],
            is_active=bool(row["is_active"]),
            is_test=bool(row["is_test"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_password_hash(self, username: str) -> str | None:
        row = self._conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return row["password_hash"] if row else None

    def create_user(
        self,
        username: str,
        password_hash: str,
        is_test: bool = False,
    ) -> User:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """
            INSERT INTO users (username, password_hash, is_active, is_test, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, ?)
            """,
            (username, password_hash, int(is_test), now, now),
        )
        self._conn.commit()
        user = self.find_by_username(username)
        assert user is not None
        return user

    def update_password_hash(self, username: str, new_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE username = ?",
            (new_hash, now, username),
        )
        self._conn.commit()

    def set_active(self, username: str, active: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE users SET is_active = ?, updated_at = ? WHERE username = ?",
            (int(active), now, username),
        )
        self._conn.commit()


class LoginAttemptRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, username: str, success: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO login_attempts (username, attempted_at, success) VALUES (?, ?, ?)",
            (username, now, int(success)),
        )
        self._conn.commit()

    def count_recent_failures(self, username: str, since_iso: str) -> int:
        """Cuenta intentos fallidos del usuario desde since_iso (inclusive)."""
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM login_attempts
            WHERE username = ? AND success = 0 AND attempted_at >= ?
            """,
            (username, since_iso),
        ).fetchone()
        return row["n"] if row else 0

    def last_failure_time(self, username: str) -> str | None:
        """Devuelve el timestamp del ultimo intento fallido, o None."""
        row = self._conn.execute(
            """
            SELECT attempted_at FROM login_attempts
            WHERE username = ? AND success = 0
            ORDER BY attempted_at DESC LIMIT 1
            """,
            (username,),
        ).fetchone()
        return row["attempted_at"] if row else None
