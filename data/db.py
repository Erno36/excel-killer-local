"""
data/db.py — Inicializacion de SQLite y migraciones.

Crea la base si no existe, aplica migraciones en orden
segun PRAGMA user_version. En modo development crea el usuario
de prueba 'dev' con contrasena 'dev1234' (RN-003).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).parent / "migrations"
CURRENT_SCHEMA_VERSION = 1


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Abre y devuelve una conexion SQLite con WAL y foreign keys."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Aplica migraciones pendientes segun PRAGMA user_version."""
    current_version: int = conn.execute("PRAGMA user_version").fetchone()[0]

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for migration_path in migration_files:
        # El nombre de archivo comienza con el numero de migracion: "001_..."
        migration_number = int(migration_path.stem.split("_")[0])
        if migration_number > current_version:
            sql = migration_path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.commit()


def init_db(db_path: Path, is_development: bool = False) -> sqlite3.Connection:
    """
    Inicializa la base de datos.
    En desarrollo, crea el usuario 'dev' si no existe (RN-003).
    Devuelve la conexion lista para usar.
    """
    conn = get_connection(db_path)
    apply_migrations(conn)

    if is_development:
        _ensure_dev_user(conn)

    return conn


def _ensure_dev_user(conn: sqlite3.Connection) -> None:
    """
    Crea el usuario 'dev' con contrasena 'dev1234' en desarrollo.
    Solo se ejecuta cuando APP_ENV=development (RN-003).
    Usa bcrypt para hashear la contrasena (RN-001).
    """
    import bcrypt  # importacion diferida para no obligar en tests sin bcrypt

    existing = conn.execute(
        "SELECT id FROM users WHERE username = ?", ("dev",)
    ).fetchone()

    if existing is None:
        password = "dev1234"
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO users (username, password_hash, is_active, is_test, created_at, updated_at)
            VALUES (?, ?, 1, 1, ?, ?)
            """,
            ("dev", hashed.decode(), now, now),
        )
        conn.commit()
