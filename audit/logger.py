"""
audit/logger.py — Logger de auditoria JSONL.

Escribe una entrada JSON por linea en .logs/cruzador_YYYY-MM-DD.jsonl.
Handler propio, separado del logging estandar de Python (D-04 del diseno).

RESTRICCION: nunca registra valores de celdas, CUILes, nombres, importes
ni ningun otro dato personal de los archivos fuente (RN-019).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from data.models import AuditEntry


class AuditLogger:
    """
    Logger de auditoria de solo-append.
    Un archivo JSONL por dia en log_dir.
    Los errores de escritura se emiten a stderr pero NO interrumpen el flujo.
    """

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Si no se puede crear el directorio en __init__, se intentara al escribir.
            pass

    def _current_log_path(self) -> Path:
        today = date.today().strftime("%Y-%m-%d")
        return self._log_dir / f"cruzador_{today}.jsonl"

    def log(self, entry: AuditEntry) -> None:
        """
        Escribe la entrada en el archivo del dia (solo append).
        Nunca lanza excepcion; errores van a stderr.
        """
        try:
            record = self._entry_to_dict(entry)
            line = json.dumps(record, ensure_ascii=False)
            log_path = self._current_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[AuditLogger] Error al escribir log: {exc}", file=sys.stderr)

    def _entry_to_dict(self, entry: AuditEntry) -> dict:
        """Convierte AuditEntry a dict serializable."""
        record: dict = {
            "timestamp": entry.timestamp,
            "usuario": entry.usuario,
            "accion": entry.accion,
        }
        if entry.archivos:
            record["archivos"] = entry.archivos
        if entry.columnas:
            record["columnas"] = entry.columnas
        if entry.filas_procesadas is not None:
            record["filas_procesadas"] = entry.filas_procesadas
        if entry.tipo_join is not None:
            record["tipo_join"] = entry.tipo_join
        if entry.duracion_ms is not None:
            record["duracion_ms"] = entry.duracion_ms
        if entry.mensaje_error is not None:
            record["mensaje_error"] = entry.mensaje_error
        if entry.extra:
            record.update(entry.extra)
        return record


def make_timestamp() -> str:
    """Devuelve timestamp ISO 8601 con zona horaria local."""
    return datetime.now(timezone.utc).astimezone().isoformat()


# ---------------------------------------------------------------------------
# Instancia global — se configura en main.py
# ---------------------------------------------------------------------------
_logger_instance: AuditLogger | None = None


def setup_logger(log_dir: Path) -> AuditLogger:
    """Inicializa el logger global. Llamar desde main.py."""
    global _logger_instance
    _logger_instance = AuditLogger(log_dir)
    return _logger_instance


def get_logger() -> AuditLogger:
    """Devuelve el logger global. Falla si no fue inicializado."""
    if _logger_instance is None:
        raise RuntimeError("AuditLogger no fue inicializado. Llamar setup_logger() primero.")
    return _logger_instance
