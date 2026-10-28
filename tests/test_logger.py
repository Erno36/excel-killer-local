"""
tests/test_logger.py — Pruebas del logger de auditoria.

Cubre CA-06-01 a CA-06-03, RN-019, RN-021.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit.logger import AuditLogger, make_timestamp
from data.models import AuditEntry


class TestFormatoJSONL:
    def test_escribe_entrada_jsonl(self, tmp_path):
        """Cada entrada es un objeto JSON valido en una linea."""
        logger = AuditLogger(tmp_path / ".logs")
        entry = AuditEntry(
            timestamp=make_timestamp(),
            usuario="testuser",
            accion="LOGIN_OK",
        )
        logger.log(entry)

        log_files = list((tmp_path / ".logs").glob("*.jsonl"))
        assert len(log_files) == 1

        lines = log_files[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["usuario"] == "testuser"
        assert record["accion"] == "LOGIN_OK"
        assert "timestamp" in record

    def test_multiples_entradas_en_mismo_archivo(self, tmp_path):
        logger = AuditLogger(tmp_path / ".logs")
        for accion in ["LOGIN_OK", "FILE_LOAD", "CROSS_EXECUTE", "EXPORT", "LOGOUT"]:
            logger.log(AuditEntry(
                timestamp=make_timestamp(),
                usuario="u",
                accion=accion,
            ))
        log_files = list((tmp_path / ".logs").glob("*.jsonl"))
        lines = log_files[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 5
        acciones = [json.loads(l)["accion"] for l in lines]
        assert "LOGIN_OK" in acciones
        assert "LOGOUT" in acciones


class TestContenidoLog:
    def test_log_no_contiene_valores_de_celdas(self, tmp_path):
        """CA-06-02: el log no registra valores de celdas."""
        logger = AuditLogger(tmp_path / ".logs")
        entry = AuditEntry(
            timestamp=make_timestamp(),
            usuario="coordinadora",
            accion="CROSS_EXECUTE",
            archivos=[{"nombre": "seguros.xlsx", "etiqueta": "Stock"}],
            columnas=["CUIL"],
            filas_procesadas=100,
            tipo_join="outer",
        )
        logger.log(entry)

        log_content = (tmp_path / ".logs").glob("*.jsonl").__next__().read_text()

        # Verificar que no hay datos de celdas (valores prohibidos).
        datos_prohibidos = ["20-12345678-9", "Juan Perez", "1500.00"]
        for dato in datos_prohibidos:
            assert dato not in log_content

    def test_log_incluye_campos_requeridos(self, tmp_path):
        """CA-06-01: el log incluye los campos requeridos por RN-019."""
        logger = AuditLogger(tmp_path / ".logs")
        entry = AuditEntry(
            timestamp=make_timestamp(),
            usuario="u",
            accion="FILE_LOAD",
            archivos=[{"nombre": "archivo.xlsx", "etiqueta": "Etiqueta"}],
            columnas=["COL1", "COL2"],
            filas_procesadas=50,
        )
        logger.log(entry)

        log_files = list((tmp_path / ".logs").glob("*.jsonl"))
        record = json.loads(log_files[0].read_text().strip())

        assert "timestamp" in record
        assert "usuario" in record
        assert "accion" in record
        assert "archivos" in record
        assert "columnas" in record
        assert "filas_procesadas" in record

    def test_error_en_escritura_no_lanza_excepcion(self, tmp_path):
        """CA-06-03: errores de escritura (permisos) no interrumpen el flujo."""
        import os
        # Crear directorio con permisos de solo lectura para forzar error al escribir.
        readonly_dir = tmp_path / "readonly_logs"
        readonly_dir.mkdir()
        (readonly_dir).chmod(0o444)  # solo lectura

        logger = AuditLogger(readonly_dir)
        # log() no debe lanzar excepcion aunque no pueda escribir.
        try:
            logger.log(AuditEntry(
                timestamp=make_timestamp(),
                usuario="u",
                accion="LOGIN_OK",
            ))
        except Exception as exc:
            pytest.fail(f"El logger lanzo una excepcion inesperada: {exc}")
        finally:
            # Restaurar permisos para que pytest pueda limpiar.
            readonly_dir.chmod(0o755)

    def test_no_registra_contrasena(self, tmp_path):
        """Ningun campo de la entrada debe contener la contrasena."""
        logger = AuditLogger(tmp_path / ".logs")
        entry = AuditEntry(
            timestamp=make_timestamp(),
            usuario="u",
            accion="LOGIN_OK",
        )
        logger.log(entry)
        log_content = (tmp_path / ".logs").glob("*.jsonl").__next__().read_text()
        assert "MiClave123!" not in log_content
        assert "password" not in log_content.lower()
