"""
tests/test_user_manager.py — Pruebas de administracion de usuarios.

Cubre HU-08, RN-001, RN-002, RN-003.
"""
from __future__ import annotations

import pytest


class TestCreacionUsuarios:
    def test_crear_usuario_nuevo(self, user_manager, db_conn):
        user = user_manager.create_user("nuevo", "Clave1234!")
        assert user.username == "nuevo"
        assert user.is_active is True
        assert user.is_test is False

    def test_hash_no_es_texto_plano(self, user_manager, db_conn):
        user_manager.create_user("hashcheck", "MiClave!")
        row = db_conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("hashcheck",)
        ).fetchone()
        assert row["password_hash"] != "MiClave!"
        assert row["password_hash"].startswith("$2b$")

    def test_usuario_duplicado_lanza_error(self, user_manager):
        user_manager.create_user("dup", "Clave!")
        with pytest.raises(Exception):  # IntegrityError de SQLite
            user_manager.create_user("dup", "OtraClave!")


class TestDesactivacion:
    def test_desactivar_usuario(self, user_manager, db_conn, auth_service):
        user_manager.create_user("activo", "Clave!")
        user_manager.deactivate_user("activo")

        row = db_conn.execute(
            "SELECT is_active FROM users WHERE username = ?", ("activo",)
        ).fetchone()
        assert row["is_active"] == 0

    def test_reactivar_usuario(self, user_manager, db_conn):
        user_manager.create_user("reactivar", "Clave!")
        user_manager.deactivate_user("reactivar")
        user_manager.activate_user("reactivar")

        row = db_conn.execute(
            "SELECT is_active FROM users WHERE username = ?", ("reactivar",)
        ).fetchone()
        assert row["is_active"] == 1


class TestReseteoContrasena:
    def test_reset_contrasena(self, user_manager, auth_service):
        user_manager.create_user("resetme", "ClaveVieja!")
        user_manager.reset_password("resetme", "ClaveNueva!")

        # La nueva contrasena funciona.
        result = auth_service.authenticate("resetme", "ClaveNueva!")
        assert result.success is True

        # La vieja ya no funciona.
        result_old = auth_service.authenticate("resetme", "ClaveVieja!")
        assert result_old.success is False
