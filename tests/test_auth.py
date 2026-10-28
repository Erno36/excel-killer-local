"""
tests/test_auth.py — Pruebas de autenticacion.

Cubre CA-01-01 a CA-01-06, RN-001, RN-003, RN-004.
"""
from __future__ import annotations

import pytest


class TestLogin:
    def test_login_exitoso(self, auth_service, sample_user):
        """CA-01-01: login exitoso con credenciales correctas."""
        result = auth_service.authenticate("testuser", "TestPass123!")
        assert result.success is True
        assert result.user is not None
        assert result.user.username == "testuser"

    def test_login_fallido_contrasena_incorrecta(self, auth_service, sample_user):
        """CA-01-02: login fallido con contrasena incorrecta."""
        result = auth_service.authenticate("testuser", "MalaClave")
        assert result.success is False
        assert result.user is None
        assert "incorrectos" in result.message.lower()

    def test_login_fallido_usuario_inexistente(self, auth_service):
        """CA-01-03: login fallido con usuario que no existe."""
        result = auth_service.authenticate("fantasma", "cualquierClave")
        assert result.success is False
        # Mismo mensaje que contrasena incorrecta (no revela si el usuario existe).
        assert "incorrectos" in result.message.lower()

    def test_mensaje_uniforme(self, auth_service, sample_user):
        """CA-01-02 + CA-01-03: el mensaje de error es identico en ambos casos."""
        result_bad_pass = auth_service.authenticate("testuser", "MalaClave")
        result_no_user = auth_service.authenticate("fantasma", "cualquierClave")
        assert result_bad_pass.message == result_no_user.message

    def test_campos_vacios(self, auth_service):
        """CA-01-06: campos vacios retornan error sin intentar autenticar."""
        result = auth_service.authenticate("", "")
        assert result.success is False
        assert "ingrese" in result.message.lower()

    def test_campo_usuario_vacio(self, auth_service):
        result = auth_service.authenticate("", "algoClave")
        assert result.success is False

    def test_campo_contrasena_vacio(self, auth_service):
        result = auth_service.authenticate("testuser", "")
        assert result.success is False


class TestPasswordHash:
    def test_hash_bcrypt_en_base(self, db_conn, user_manager):
        """CA-01-04: la contrasena se almacena como hash bcrypt."""
        user_manager.create_user("hashtest", "MiClave123!")
        row = db_conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("hashtest",)
        ).fetchone()
        hashed = row["password_hash"]
        # No es texto plano.
        assert hashed != "MiClave123!"
        # No es MD5 (32 chars) ni SHA1 (40 chars).
        assert len(hashed) not in (32, 40)
        # Es bcrypt.
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_hash_factor_costo_12(self, db_conn, user_manager):
        """RN-001: factor de costo >= 12."""
        user_manager.create_user("costtest", "Clave1234!")
        row = db_conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("costtest",)
        ).fetchone()
        # El hash bcrypt incluye el factor en el segundo campo: $2b$12$...
        parts = row["password_hash"].split("$")
        factor = int(parts[2])
        assert factor >= 12


class TestDevUser:
    def test_dev_user_no_en_produccion(self, db_conn):
        """CA-01-05: el usuario dev no existe si no se crea en desarrollo."""
        row = db_conn.execute(
            "SELECT id FROM users WHERE username = 'dev'",
        ).fetchone()
        # La base de test no crea usuario dev (no llamamos init_db con is_development=True).
        assert row is None

    def test_dev_user_se_crea_en_desarrollo(self, tmp_path):
        """RN-003: el usuario dev se crea en modo development."""
        from data.db import init_db
        db_path = tmp_path / "test_dev.db"
        conn = init_db(db_path, is_development=True)
        row = conn.execute(
            "SELECT username, is_test FROM users WHERE username = 'dev'"
        ).fetchone()
        assert row is not None
        assert row["username"] == "dev"
        assert row["is_test"] == 1


class TestBloqueo:
    def test_bloqueo_tras_max_intentos(self, db_conn):
        """RN-004: bloqueo tras 5 intentos fallidos."""
        from auth.service import AuthService, UserManager
        mgr = UserManager(db_conn)
        mgr.create_user("bloqueado", "ClaveSegura1!")
        auth = AuthService(db_conn, max_attempts=3, lockout_minutes=5)

        for _ in range(3):
            auth.authenticate("bloqueado", "MalaClave")

        result = auth.authenticate("bloqueado", "ClaveSegura1!")
        assert result.success is False
        assert "bloqueada" in result.message.lower()

    def test_usuario_inactivo_no_puede_ingresar(self, auth_service, user_manager, db_conn):
        """Usuarios desactivados no pueden ingresar."""
        user_manager.create_user("inactivo", "Clave123!")
        user_manager.deactivate_user("inactivo")
        result = auth_service.authenticate("inactivo", "Clave123!")
        assert result.success is False
