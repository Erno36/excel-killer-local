"""
engine/column_matcher.py — Utilidades de clasificacion de columnas y sugerencia de pares.
Sin imports de PySide6.
RN-019: no accede a valores de celdas, solo a nombres de columnas y metadatos de tipo.
"""
from __future__ import annotations

import re

import pandas as pd


def infer_column_type(series: pd.Series) -> str:
    """
    Infiere el tipo semantico de una columna pandas.
    Retorna "numero", "fecha" o "texto".
    Reutiliza la misma logica que engine/cross.py._infer_type.
    """
    non_null = series.dropna()
    if non_null.empty:
        return "texto"

    # Datetime nativo
    if pd.api.types.is_datetime64_any_dtype(series):
        return "fecha"

    # Numerico nativo
    if pd.api.types.is_numeric_dtype(series):
        return "numero"

    # Intento numerico sobre texto
    numeric_count = pd.to_numeric(non_null, errors="coerce").notna().sum()
    if numeric_count / len(non_null) > 0.8:
        return "numero"

    # Intento de fechas sobre texto
    try:
        import warnings as _w
        with _w.catch_warnings():
            _w.simplefilter("ignore")
            date_count = pd.to_datetime(
                non_null, errors="coerce", format="mixed", dayfirst=True
            ).notna().sum()
        if date_count / len(non_null) > 0.8:
            return "fecha"
    except Exception:
        pass

    return "texto"


TYPE_ICON: dict[str, str] = {
    "numero": "\U0001f522",  # 🔢
    "fecha":  "\U0001f4c5",  # 📅
    "texto":  "\U0001f524",  # 🔤
}


def _normalize_name(name: str) -> str:
    """Normaliza un nombre de columna para comparacion: lowercase, sin espacios ni guiones."""
    return re.sub(r"[\s\-_./]", "", name.lower().strip())


def suggest_pairs(
    left_columns: list[str],
    right_columns: list[str],
) -> list[tuple[str, str]]:
    """
    Sugiere pares de columnas para el cruce por similitud de nombre.

    Reglas (en orden de prioridad):
    1. Match exacto tras normalizacion (strip + lowercase + eliminar separadores).
    2. Una contiene a la otra (la mas corta esta contenida en la mas larga).

    Retorna lista de (col_izq, col_der) sin repeticiones.
    Cada columna aparece maximo una vez en los pares sugeridos.
    """
    pairs: list[tuple[str, str]] = []
    used_left: set[str] = set()
    used_right: set[str] = set()

    norm_left  = {c: _normalize_name(c) for c in left_columns}
    norm_right = {c: _normalize_name(c) for c in right_columns}

    # Pasada 1: match exacto
    for lc, ln in norm_left.items():
        for rc, rn in norm_right.items():
            if rc in used_right:
                continue
            if ln == rn and lc not in used_left:
                pairs.append((lc, rc))
                used_left.add(lc)
                used_right.add(rc)
                break

    # Pasada 2: contencion (una contiene a la otra)
    for lc, ln in norm_left.items():
        if lc in used_left:
            continue
        for rc, rn in norm_right.items():
            if rc in used_right:
                continue
            if (ln in rn or rn in ln) and len(ln) >= 3 and len(rn) >= 3:
                pairs.append((lc, rc))
                used_left.add(lc)
                used_right.add(rc)
                break

    return pairs
