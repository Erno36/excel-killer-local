"""
engine/filter_ops.py — Logica pura de filtrado sobre DataFrames.

Sin imports de PySide6: este modulo es testeable en forma aislada.

Operadores soportados:
    contiene, igual_a, empieza_con, mayor_que, menor_que, es_vacio, no_es_vacio,
    fecha_antes_de, fecha_despues_de, fecha_entre

RN-019: esta capa nunca registra valores de celdas ni valores de filtro en logs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from engine._date_utils import parse_date_flexible


# ---------------------------------------------------------------------------
# Dataclass de condicion de filtro
# ---------------------------------------------------------------------------

OPERADORES_VALIDOS = frozenset(
    {
        "contiene",
        "igual_a",
        "empieza_con",
        "mayor_que",
        "menor_que",
        "es_vacio",
        "no_es_vacio",
        "fecha_antes_de",    # columna <= value  (inclusive)
        "fecha_despues_de",  # columna >= value  (inclusive)
        "fecha_entre",       # value <= columna <= value2
    }
)


@dataclass
class FilterCondition:
    """
    Condicion de filtro sobre una columna del DataFrame.

    Atributos:
        column:   nombre de la columna sobre la que se aplica la condicion.
        operator: uno de OPERADORES_VALIDOS.
        value:    cadena que el usuario ingreso como valor de comparacion.
                  Ignorado para 'es_vacio' y 'no_es_vacio'.
        value2:   usado unicamente por 'fecha_entre' como fecha "hasta" (inclusive).
    """

    column: str
    operator: str
    value: str = ""
    value2: str = ""   # usado por fecha_entre

    def __post_init__(self) -> None:
        if self.operator not in OPERADORES_VALIDOS:
            raise ValueError(
                f"Operador '{self.operator}' no reconocido. "
                f"Validos: {sorted(OPERADORES_VALIDOS)}"
            )


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------

def apply_filters(
    df: pd.DataFrame,
    conditions: Sequence[FilterCondition],
    quick_search: str = "",
) -> pd.DataFrame:
    """
    Aplica condiciones de filtro (AND) y busqueda rapida sobre *df*.

    Parametros:
        df:           DataFrame fuente (no se modifica).
        conditions:   lista de FilterCondition; se aplican en AND.
        quick_search: texto libre; filtra filas donde CUALQUIER columna
                      lo contenga (case-insensitive, strip).

    Devuelve:
        Nuevo DataFrame con las filas que cumplen todos los criterios.
        Los indices del DataFrame original se preservan.
    """
    if df.empty:
        return df.copy()

    mask = pd.Series([True] * len(df), index=df.index)

    # --- Condiciones de columna (AND) ---
    for cond in conditions:
        if cond.column not in df.columns:
            # Columna inexistente: condicion no aplica filas (mask False)
            mask &= False
            continue
        col_mask = _apply_single_condition(df, cond)
        mask &= col_mask

    # --- Busqueda rapida en todas las columnas ---
    qs = quick_search.strip()
    if qs:
        qs_lower = qs.lower()
        any_col_mask = pd.Series([False] * len(df), index=df.index)
        for col in df.columns:
            col_str = df[col].fillna("").astype(str).str.lower()
            any_col_mask |= col_str.str.contains(qs_lower, regex=False, na=False)
        mask &= any_col_mask

    return df[mask].copy()


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _apply_single_condition(df: pd.DataFrame, cond: FilterCondition) -> pd.Series:
    """Devuelve una mascara booleana para una sola condicion."""
    col = df[cond.column]
    op = cond.operator
    val = cond.value

    if op == "es_vacio":
        return col.isna() | (col.astype(str).str.strip() == "")

    if op == "no_es_vacio":
        return ~(col.isna() | (col.astype(str).str.strip() == ""))

    # --- Operadores de fecha ---
    if op in ("fecha_antes_de", "fecha_despues_de", "fecha_entre"):
        return _date_comparison(col, op, val, cond.value2)

    # Para los operadores con valor, si val esta vacio se asume "sin restriccion"
    if val == "":
        return pd.Series([True] * len(df), index=df.index)

    col_str = col.fillna("").astype(str)
    val_lower = val.lower()

    if op == "contiene":
        return col_str.str.lower().str.contains(val_lower, regex=False, na=False)

    if op == "igual_a":
        return col_str.str.lower() == val_lower

    if op == "empieza_con":
        return col_str.str.lower().str.startswith(val_lower, na=False)

    if op in ("mayor_que", "menor_que"):
        return _numeric_comparison(col, op, val)

    # Fallback: no restriccion
    return pd.Series([True] * len(df), index=df.index)


def _date_comparison(
    col: pd.Series,
    op: str,
    value: str,
    value2: str,
) -> pd.Series:
    """
    Compara cada celda de *col* contra una o dos fechas (value / value2).

    Comportamiento conservador:
    - Celdas que no parsean como fecha -> False (no se incluyen).
    - Si value (o value2 para fecha_entre) no parsea -> mascara False para todas.
    """
    false_mask = pd.Series([False] * len(col), index=col.index)

    # Parsear fecha(s) de comparacion.
    threshold = parse_date_flexible(value)
    if threshold is None:
        return false_mask

    if op == "fecha_entre":
        threshold2 = parse_date_flexible(value2)
        if threshold2 is None:
            return false_mask

    # Parsear cada celda de la columna.
    def _parse_cell(v) -> object:
        if pd.isna(v):
            return None
        return parse_date_flexible(str(v))

    parsed = col.apply(_parse_cell)
    parseable_mask = parsed.notna()

    if op == "fecha_antes_de":
        # Inclusivo: columna <= threshold
        result = parsed.apply(lambda d: d <= threshold if d is not None else False)
        return result & parseable_mask

    if op == "fecha_despues_de":
        # Inclusivo: columna >= threshold
        result = parsed.apply(lambda d: d >= threshold if d is not None else False)
        return result & parseable_mask

    if op == "fecha_entre":
        result = parsed.apply(
            lambda d: (threshold <= d <= threshold2) if d is not None else False
        )
        return result & parseable_mask

    # Fallback (no deberia llegar aqui)
    return false_mask


def _numeric_comparison(col: pd.Series, op: str, val: str) -> pd.Series:
    """
    Compara numericamente si es posible; si la columna no es numerica,
    intenta parsear ambos lados como float. En caso de error, devuelve
    mascara False para todas las filas (comportamiento conservador).
    """
    try:
        threshold = float(val)
    except (ValueError, TypeError):
        return pd.Series([False] * len(col), index=col.index)

    numeric_col = pd.to_numeric(col, errors="coerce")
    valid = numeric_col.notna()

    if op == "mayor_que":
        result = numeric_col > threshold
    else:  # menor_que
        result = numeric_col < threshold

    # Filas no parseables quedan en False (notna es False -> result es NaN -> .fillna(False))
    return result.fillna(False) & valid
