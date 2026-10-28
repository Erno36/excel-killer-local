"""
tests/conftest.py — Fixtures compartidos para todos los tests.

- Base SQLite en memoria.
- Archivos Excel sinteticos temporales.
- Logger de auditoria en directorio temporal.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from auth.service import AuthService, SessionManager, UserManager
from audit.logger import AuditLogger
from data.db import apply_migrations


@pytest.fixture
def db_conn():
    """Conexion SQLite en memoria con migraciones aplicadas."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def user_manager(db_conn):
    return UserManager(db_conn)


@pytest.fixture
def auth_service(db_conn):
    return AuthService(db_conn, max_attempts=5, lockout_minutes=5)


@pytest.fixture
def session_manager():
    return SessionManager(timeout_minutes=30)


@pytest.fixture
def audit_logger(tmp_path):
    """Logger que escribe en directorio temporal."""
    log_dir = tmp_path / ".logs"
    return AuditLogger(log_dir)


@pytest.fixture
def sample_user(user_manager):
    """Crea un usuario de prueba y lo devuelve."""
    return user_manager.create_user("testuser", "TestPass123!", is_test=True)


@pytest.fixture
def excel_seguros(tmp_path) -> Path:
    """Excel sintetico de seguros con CUILes ficticios."""
    df = pd.DataFrame({
        "CUIL": ["20-11111111-1", "20-22222222-2", "20-33333333-3", "20-44444444-4"],
        "nombre_producto": ["Seguro Vida", "Seguro Auto", "Seguro Hogar", "Seguro Vida"],
        "estado": ["activo", "activo", "cancelado", "activo"],
        "broker": ["Broker A", "Broker B", "Broker A", "Broker C"],
        "importe_prima": ["1500.00", "2300.00", "800.00", "1200.00"],
    })
    path = tmp_path / "seguros_test.xlsx"
    df.to_excel(path, index=False)
    return path


@pytest.fixture
def excel_bajas(tmp_path) -> Path:
    """Excel sintetico de bajas."""
    df = pd.DataFrame({
        "CUIL": ["20-22222222-2", "20-33333333-3", "20-55555555-5"],
        "motivo_baja": ["mora", "fallecimiento", "mora"],
        "fecha_baja": ["2026-08-01", "2026-07-15", "2026-09-01"],
    })
    path = tmp_path / "bajas_test.xlsx"
    df.to_excel(path, index=False)
    return path


@pytest.fixture
def excel_empty(tmp_path) -> Path:
    """Excel con encabezado pero sin filas de datos."""
    df = pd.DataFrame(columns=["CUIL", "nombre"])
    path = tmp_path / "vacio_test.xlsx"
    df.to_excel(path, index=False)
    return path


@pytest.fixture
def excel_with_duplicates(tmp_path) -> Path:
    """Excel con columnas duplicadas."""
    df = pd.DataFrame([[1, "a", "b"]], columns=["CUIL", "Importe", "Importe"])
    path = tmp_path / "duplicados_test.xlsx"
    # Escribir manualmente para forzar columnas duplicadas.
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["CUIL", "Importe", "Importe"])
    ws.append(["20-11111111-1", "1500", "2000"])
    wb.save(path)
    return path
