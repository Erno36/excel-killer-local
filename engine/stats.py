"""
engine/stats.py — Calculo de estadisticas del resultado del cruce.

Sin imports de PySide6. Solo stdlib + pandas + numpy.

RN-019: ningun valor de celda se incluye en los resultados de estadisticas
        que se loggean. Los StatsResult contienen solo agregados.

RN-STATS-003: el log de auditoria solo puede contener:
  - Nombres de columnas analizadas.
  - Conteos agregados (cantidad de nulos, valores unicos, filas).
  - Tipo de join.
  - Duracion del calculo.

  El log NO puede contener: sumas, promedios, min/max de numericos,
  fechas min/max de columnas de fecha, valores de top-3.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd

from engine._date_utils import parse_date_flexible

# Palabras clave para detectar columnas identificadoras (RN-STATS-005).
# Una columna numerica cuyo nombre contenga alguna de estas cadenas
# (case-insensitive) se excluye de estadisticas de importe.
_IDENTIFIER_KEYWORDS: tuple[str, ...] = (
    "cuil", "cuit", "dni", "cod_", "codigo", "id_", "_id",
    "nro_", "numero_", "cuenta", "poliza", "expediente",
)


# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------

@dataclass
class ColumnStats:
    name: str
    dtype_label: str       # "texto", "numero", "fecha", "mixto", "vacio", "identificador"
    total_rows: int
    null_count: int
    null_pct: float        # 0.0 - 100.0
    unique_count: int
    is_identifier: bool = False   # True si se excluye de stats numericas (RN-STATS-005)
    # Fechas
    date_min: str | None = None   # formato dd/mm/aaaa
    date_max: str | None = None
    # Numericos
    num_sum: float | None = None
    num_mean: float | None = None
    num_min: float | None = None
    num_max: float | None = None
    num_effective: int | None = None  # valores incluidos en calculo


@dataclass
class StatsResult:
    total_rows: int
    total_cols: int
    matched_rows: int | None     # None si no disponible
    left_only_rows: int | None
    right_only_rows: int | None
    columns: list[ColumnStats] = field(default_factory=list)
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------

def compute_stats(
    df: pd.DataFrame,
    matched_rows: int | None = None,
    left_only_rows: int | None = None,
    right_only_rows: int | None = None,
) -> StatsResult:
    """
    Calcula estadisticas completas del DataFrame.

    Retorna StatsResult. No lanza excepciones (usa defaults en error).
    RN-019: no almacena valores individuales de celdas.

    Parametros:
        df: DataFrame a analizar.
        matched_rows: conteo de filas con match de ambos lados (de CrossResult).
        left_only_rows: conteo de filas solo en archivo izquierdo.
        right_only_rows: conteo de filas solo en archivo derecho.
    """
    t0 = time.perf_counter()

    total_rows = len(df)
    total_cols = len(df.columns)
    col_stats: list[ColumnStats] = []

    for col_name in df.columns:
        try:
            col_stats.append(_compute_column_stats(df[col_name], col_name))
        except Exception:
            # Columna con error: registrar con valores minimos, sin propagar.
            col_stats.append(ColumnStats(
                name=str(col_name),
                dtype_label="mixto",
                total_rows=total_rows,
                null_count=0,
                null_pct=0.0,
                unique_count=0,
            ))

    duration_ms = (time.perf_counter() - t0) * 1000

    return StatsResult(
        total_rows=total_rows,
        total_cols=total_cols,
        matched_rows=matched_rows,
        left_only_rows=left_only_rows,
        right_only_rows=right_only_rows,
        columns=col_stats,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Funciones internas
# ---------------------------------------------------------------------------

def _compute_column_stats(series: pd.Series, name: str) -> ColumnStats:
    """Computa estadisticas de una sola columna. No lanza excepciones."""
    total = len(series)
    null_count = int(series.isna().sum())
    null_pct = (null_count / total * 100) if total > 0 else 0.0

    non_null = series.dropna()
    unique_count = int(non_null.nunique()) if len(non_null) > 0 else 0

    dtype_label, is_id, date_min, date_max, num_sum, num_mean, num_min, num_max, num_eff = \
        _infer_and_compute(series, non_null, str(name))

    return ColumnStats(
        name=str(name),
        dtype_label=dtype_label,
        total_rows=total,
        null_count=null_count,
        null_pct=round(null_pct, 1),
        unique_count=unique_count,
        is_identifier=is_id,
        date_min=date_min,
        date_max=date_max,
        num_sum=num_sum,
        num_mean=num_mean,
        num_min=num_min,
        num_max=num_max,
        num_effective=num_eff,
    )


def _is_identifier_column(col_name: str) -> bool:
    """
    Retorna True si el nombre de columna sugiere que es un identificador
    (CUIL, DNI, codigo, etc.) segun RN-STATS-005.
    """
    name_lower = col_name.lower()
    return any(kw in name_lower for kw in _IDENTIFIER_KEYWORDS)


def _infer_and_compute(
    series: pd.Series,
    non_null: pd.Series,
    col_name: str,
) -> "tuple[str, bool, str | None, str | None, float | None, float | None, float | None, float | None, int | None]":
    """
    Detecta tipo y calcula stats especializadas.

    Retorna:
        (dtype_label, is_identifier, date_min, date_max,
         num_sum, num_mean, num_min, num_max, num_effective)
    """
    if non_null.empty:
        return "vacio", False, None, None, None, None, None, None, None

    # --- Columna de fecha nativa (datetime/timedelta) ---
    if pd.api.types.is_datetime64_any_dtype(series):
        valid_dates = non_null.dropna()
        if not valid_dates.empty:
            fmt = "%d/%m/%Y"
            date_min_str = valid_dates.min().strftime(fmt)
            date_max_str = valid_dates.max().strftime(fmt)
            return "fecha", False, date_min_str, date_max_str, None, None, None, None, None
        return "fecha", False, None, None, None, None, None, None, None

    # --- Columna numerica nativa ---
    if pd.api.types.is_numeric_dtype(series):
        # Verificar si es identificador (RN-STATS-005).
        if _is_identifier_column(col_name):
            return "identificador", True, None, None, None, None, None, None, None

        try:
            valid = non_null.dropna()
            effective = int(valid.count())
            return (
                "numero",
                False,
                None, None,
                float(valid.sum()),
                float(valid.mean()),
                float(valid.min()),
                float(valid.max()),
                effective,
            )
        except Exception:
            pass

    # --- Intento numerico sobre texto (> 80% parseables) ---
    numeric_parsed = pd.to_numeric(non_null, errors="coerce")
    numeric_ok = int(numeric_parsed.notna().sum())
    if len(non_null) > 0 and numeric_ok / len(non_null) > 0.8:
        if _is_identifier_column(col_name):
            return "identificador", True, None, None, None, None, None, None, None
        try:
            valid = numeric_parsed.dropna()
            effective = int(valid.count())
            return (
                "numero",
                False,
                None, None,
                float(valid.sum()),
                float(valid.mean()),
                float(valid.min()),
                float(valid.max()),
                effective,
            )
        except Exception:
            pass

    # --- Intento de fechas (> 70% parseables) ---
    str_series = non_null.astype(str).str.strip()
    parsed_dates = str_series.apply(parse_date_flexible)
    dates_ok = int(parsed_dates.notna().sum())
    if len(non_null) > 0 and dates_ok / len(non_null) > 0.8:
        valid_dates = parsed_dates.dropna()
        if not valid_dates.empty:
            date_min_dt = valid_dates.min()
            date_max_dt = valid_dates.max()
            fmt = "%d/%m/%Y"
            return (
                "fecha",
                False,
                date_min_dt.strftime(fmt),
                date_max_dt.strftime(fmt),
                None, None, None, None, None,
            )

    return "texto", False, None, None, None, None, None, None, None
