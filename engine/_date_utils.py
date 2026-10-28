"""
engine/_date_utils.py — Utilidades compartidas de parseo de fechas.

Sin imports de PySide6. Usado por filter_ops.py y cleansing.py para evitar
duplicacion de logica de parseo flexible de fechas.

RN-019: este modulo no registra ni loguea valores de celdas ni fechas
ingresadas por el usuario.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

# Formatos de fecha intentados en orden de prioridad.
# El orden importa: primero los formatos con separador de cuatro digitos en el anyo
# para evitar ambiguedad dd-mm-aa vs mm-dd-aa.
DATE_FORMATS: list[str] = [
    "%d/%m/%Y",   # 25/10/2025  (formato argentino / europeo)
    "%Y-%m-%d",   # 2025-10-25  (ISO 8601)
    "%d-%m-%Y",   # 25-10-2025
    "%m/%d/%Y",   # 10/25/2025  (formato estadounidense)
    "%Y/%m/%d",   # 2025/10/25
]


def parse_date_flexible(s: str) -> Optional[datetime]:
    """
    Intenta parsear la cadena *s* con cada formato de DATE_FORMATS en orden.

    Retorna el primer datetime que parsee correctamente, o None si ninguno
    lo logra (comportamiento conservador: no lanza excepcion).

    Parametros:
        s: cadena a parsear (se hace strip() antes de intentar).

    Retorna:
        datetime o None.
    """
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None
