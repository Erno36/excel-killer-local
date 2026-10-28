"""
auth/service.py — Logica de autenticacion, sesion y administracion de usuarios.

RN-001: bcrypt con factor >= 12.
RN-004: bloqueo tras max intentos fallidos.
RN-005: timeout de sesion por inactividad.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt

from auth.repository import LoginAttemptRepository, UserRepository
from data.models import User


# ---------------------------------------------------------------------------
# Resultado de autenticacion
# ---------------------------------------------------------------------------

@dataclass
class AuthResult:
    success: bool
    user: User | None
    message: str        # mensaje para mostrar en la UI; nunca stack trace


# ---------------------------------------------------------------------------
# Autenticacion
# ---------------------------------------------------------------------------

class AuthService:
    """
    Verifica credenciales y gestiona el bloqueo por intentos fallidos.
    No guarda estado entre llamadas: es stateless (la sesion la gestiona SessionManager).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        max_attempts: int = 5,
        lockout_minutes: int = 5,
    ) -> None:
        self._users = UserRepository(conn)
        self._attempts = LoginAttemptRepository(conn)
        self._max_attempts = max_attempts
        self._lockout_minutes = lockout_minutes

    def authenticate(self, username: str, password: str) -> AuthResult:
        """
        Verifica credenciales contra la base.
        Mensaje de error uniforme para usuario/contrasena incorrectos
        (no indica cual de los dos es el error — CA-01-02 y CA-01-03).
        """
        if not username or not password:
            return AuthResult(
                success=False,
                user=None,
                message="Ingrese usuario y contrasena.",
            )

        # Verificar bloqueo activo.
        if self._is_locked(username):
            return AuthResult(
                success=False,
                user=None,
                message=(
                    f"La cuenta esta bloqueada temporalmente por demasiados intentos fallidos. "
                    f"Intentelo nuevamente en {self._lockout_minutes} minutos."
                ),
            )

        user = self._users.find_by_username(username)
        password_hash = self._users.get_password_hash(username)

        # Evitar timing attack: siempre verificar contra un hash aunque el usuario no exista.
        dummy_hash = "$2b$12$invalidhashfortimingequalityprotection0000000000000000"
        hash_to_check = password_hash if password_hash else dummy_hash

        try:
            password_ok = bcrypt.checkpw(password.encode(), hash_to_check.encode())
        except Exception:
            password_ok = False

        if user is None or not user.is_active or not password_ok:
            self._attempts.record(username, success=False)
            return AuthResult(
                success=False,
                user=None,
                message="Usuario o contrasena incorrectos.",
            )

        # Login exitoso.
        self._attempts.record(username, success=True)
        return AuthResult(success=True, user=user, message="")

    def _is_locked(self, username: str) -> bool:
        """
        True si el usuario tiene >= max_attempts fallos en la ventana de lockout.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=self._lockout_minutes)
        ).isoformat()
        failures = self._attempts.count_recent_failures(username, cutoff)
        return failures >= self._max_attempts


# ---------------------------------------------------------------------------
# Sesion
# ---------------------------------------------------------------------------

class SessionManager:
    """
    Mantiene el estado de sesion en memoria.
    No persiste nada en disco (D-05 del diseno).
    """

    def __init__(self, timeout_minutes: int = 30) -> None:
        self._user: User | None = None
        self._last_activity: datetime | None = None
        self._timeout = timedelta(minutes=timeout_minutes)

    def start(self, user: User) -> None:
        self._user = user
        self._refresh()

    def end(self) -> None:
        self._user = None
        self._last_activity = None

    def current_user(self) -> User | None:
        return self._user

    def refresh_activity(self) -> None:
        if self._user is not None:
            self._refresh()

    def is_expired(self) -> bool:
        if self._user is None or self._last_activity is None:
            return True
        elapsed = datetime.now(timezone.utc) - self._last_activity
        return elapsed > self._timeout

    def _refresh(self) -> None:
        self._last_activity = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Administracion de usuarios (sin UI en V1 — D-06)
# ---------------------------------------------------------------------------

class UserManager:
    """
    Alta, baja y reseteo de contrasenas.
    Operable desde scripts de consola o directamente via SQLite.
    """

    BCRYPT_ROUNDS = 12  # RN-001

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._users = UserRepository(conn)

    def create_user(self, username: str, password: str, is_test: bool = False) -> User:
        """Crea un usuario nuevo con contrasena hasheada en bcrypt."""
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=self.BCRYPT_ROUNDS))
        return self._users.create_user(username, hashed.decode(), is_test=is_test)

    def reset_password(self, username: str, new_password: str) -> None:
        """Resetea la contrasena de un usuario existente."""
        hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(rounds=self.BCRYPT_ROUNDS))
        self._users.update_password_hash(username, hashed.decode())

    def deactivate_user(self, username: str) -> None:
        """Desactiva un usuario (no lo borra)."""
        self._users.set_active(username, active=False)

    def activate_user(self, username: str) -> None:
        """Reactiva un usuario desactivado."""
        self._users.set_active(username, active=True)
