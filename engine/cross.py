"""
engine/cross.py — Motor de cruce de N >= 2 DataFrames.

SIN importaciones de PySide6. Testeable sin GUI (RT-06).

Implementa cadena de joins secuencial (D-03 del diseno).
Soporta inner / left / outer.
Soporta claves compuestas por paso via steps_key_pairs (D-03b).
Normalizacion de claves: strip + lowercase, opcion del usuario (D-07).
Modo dry_run: solo valida y estima, no produce DataFrame (RNF-08).
"""
from __future__ import annotations

import time

import pandas as pd

from data.models import CrossConfig, CrossResult, FileEntry


# ---------------------------------------------------------------------------
# Excepciones del motor
# ---------------------------------------------------------------------------

class CrossConfigError(Exception):
    """Configuracion invalida: columna inexistente, tipo incompatible, etc."""
    pass


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _resolve_steps(config: CrossConfig) -> list[list[tuple[str, str]]]:
    """
    Devuelve la lista de pasos, donde cada paso es una lista de pares de columnas.
    Usa steps_key_pairs si esta presente; cae a key_pairs como compat backward.
    """
    n_steps = len(config.file_entries) - 1

    if config.steps_key_pairs:
        steps = config.steps_key_pairs
        if len(steps) != n_steps:
            raise CrossConfigError(
                f"Se necesitan {n_steps} paso(s) de columnas clave "
                f"para cruzar {len(config.file_entries)} archivos, "
                f"pero se recibieron {len(steps)}."
            )
        for idx, step in enumerate(steps):
            if not step:
                raise CrossConfigError(
                    f"El paso {idx + 1} no tiene ninguna columna clave definida. "
                    "Cada cruce debe tener al menos una columna clave."
                )
        return steps

    # Backward compat: key_pairs plana
    if len(config.key_pairs) != n_steps:
        raise CrossConfigError(
            f"Se necesitan {n_steps} par(es) de columnas clave "
            f"para cruzar {len(config.file_entries)} archivos."
        )
    return [[(kp[0], kp[1])] for kp in config.key_pairs]


# ---------------------------------------------------------------------------
# Motor principal
# ---------------------------------------------------------------------------

def execute_cross(config: CrossConfig, dry_run: bool = False) -> CrossResult:
    """
    Ejecuta el cruce segun CrossConfig.

    Si dry_run=True: valida columnas y estima filas; devuelve CrossResult con df=None.
    Si dry_run=False: ejecuta el join y devuelve el DataFrame resultado.

    Lanza CrossConfigError si la configuracion es invalida.
    """
    if len(config.file_entries) < 2:
        raise CrossConfigError("Se necesitan al menos 2 archivos para el cruce.")

    steps = _resolve_steps(config)

    warnings: list[str] = []
    columns_used: list[str] = []

    # Validar columnas clave en cada paso.
    for i, step_pairs in enumerate(steps):
        entry_left = config.file_entries[i]
        entry_right = config.file_entries[i + 1]

        for col_left, col_right in step_pairs:
            if col_left not in entry_left.df.columns:
                available = ", ".join(entry_left.df.columns.tolist())
                raise CrossConfigError(
                    f"La columna '{col_left}' no se encontro en '{entry_left.label}'. "
                    f"Columnas disponibles: {available}."
                )
            if col_right not in entry_right.df.columns:
                available = ", ".join(entry_right.df.columns.tolist())
                raise CrossConfigError(
                    f"La columna '{col_right}' no se encontro en '{entry_right.label}'. "
                    f"Columnas disponibles: {available}."
                )

            columns_used.extend([col_left, col_right])

            # Advertencia de tipos incompatibles (CA-04-04).
            type_left = _infer_type(entry_left.df[col_left])
            type_right = _infer_type(entry_right.df[col_right])
            if type_left != type_right and not config.normalize_keys:
                warnings.append(
                    f"Las columnas '{col_left}' ({entry_left.label}) y "
                    f"'{col_right}' ({entry_right.label}) tienen tipos distintos "
                    f"({type_left} vs {type_right}). "
                    "El cruce puede producir resultados inesperados. "
                    "Activa la normalizacion para intentar el cruce igual."
                )

    # Modo dry_run: retornar sin ejecutar.
    if dry_run:
        estimated_rows = max(len(e.df) for e in config.file_entries)
        return CrossResult(
            df=None,
            row_count=estimated_rows,
            join_type=config.join_type,
            columns_used=list(set(columns_used)),
            warnings=warnings,
            duration_ms=0.0,
        )

    # Ejecutar la cadena de joins.
    t_start = time.perf_counter()

    result_df, matched, left_only, right_only = _execute_join_chain(config, steps, warnings)

    duration_ms = (time.perf_counter() - t_start) * 1000

    # Advertencia si no hay coincidencias (inner join con 0 filas).
    if config.join_type == "inner" and len(result_df) == 0:
        warnings.append(
            "El cruce no produjo coincidencias. "
            "Revisa que los valores de las columnas clave coincidan "
            "y el tipo de cruce seleccionado."
        )

    return CrossResult(
        df=result_df,
        row_count=len(result_df),
        join_type=config.join_type,
        columns_used=list(set(columns_used)),
        warnings=warnings,
        duration_ms=duration_ms,
        matched_rows=matched,
        left_only_rows=left_only,
        right_only_rows=right_only,
    )


# ---------------------------------------------------------------------------
# Implementacion interna
# ---------------------------------------------------------------------------

def _execute_join_chain(
    config: CrossConfig,
    steps: list[list[tuple[str, str]]],
    warnings: list[str],
) -> "tuple[pd.DataFrame, int | None, int | None, int | None]":
    """
    Construye la cadena de merges:
    resultado = A ⋈ B ⋈ C ⋈ ...
    Cada paso puede usar una o mas columnas clave (clave compuesta).

    Retorna (df, matched_rows, left_only_rows, right_only_rows).
    Para inner join: matched = len(df), left_only = 0, right_only = 0.
    Para left/outer: usa indicator=True en el ultimo paso para obtener conteos.
    """
    pandas_how = _map_join_type(config.join_type)
    accumulated = _prepare_df(config.file_entries[0], config.normalize_keys)

    last_i = len(steps) - 1
    _matched: int | None = None
    _left_only: int | None = None
    _right_only: int | None = None

    for i, step_pairs in enumerate(steps):
        right_entry = config.file_entries[i + 1]
        right_df = _prepare_df(right_entry, config.normalize_keys)

        left_label = config.file_entries[i].label
        right_label = right_entry.label

        # Renombrar columnas derecha para que coincidan con las izquierdas
        # (para poder usar 'on=' en el merge y mantener un solo nombre).
        rename_map = {
            col_right: col_left
            for col_left, col_right in step_pairs
            if col_left != col_right and col_right in right_df.columns
        }
        if rename_map:
            right_df = right_df.rename(columns=rename_map)

        join_keys = [col_left for col_left, _ in step_pairs]

        is_last = (i == last_i)
        use_indicator = is_last and pandas_how != "inner"

        if use_indicator:
            accumulated = pd.merge(
                accumulated,
                right_df,
                on=join_keys,
                how=pandas_how,
                suffixes=(f"_{left_label}", f"_{right_label}"),
                indicator=True,
            )
            # Extraer conteos antes de dropear la columna _merge.
            _matched = int((accumulated["_merge"] == "both").sum())
            _left_only = int((accumulated["_merge"] == "left_only").sum())
            _right_only = int((accumulated["_merge"] == "right_only").sum())
            accumulated = accumulated.drop(columns=["_merge"])
        else:
            accumulated = pd.merge(
                accumulated,
                right_df,
                on=join_keys,
                how=pandas_how,
                suffixes=(f"_{left_label}", f"_{right_label}"),
            )

    # Para inner join: todas las filas son coincidencias.
    if pandas_how == "inner":
        _matched = len(accumulated)
        _left_only = 0
        _right_only = 0

    return accumulated, _matched, _left_only, _right_only


def _prepare_df(entry: FileEntry, normalize: bool) -> pd.DataFrame:
    """
    Copia el DataFrame del FileEntry.
    Si normalize=True, aplica strip + lowercase a TODAS las celdas de texto
    de las columnas de tipo string (para comparacion; los valores originales
    se pierden en el resultado — supuesto aceptado segun D-07).
    """
    df = entry.df.copy()
    if normalize:
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].apply(
                    lambda v: v.strip().lower() if isinstance(v, str) else v
                )
    return df


def _map_join_type(join_type: str) -> str:
    mapping = {"inner": "inner", "left": "left", "outer": "outer"}
    return mapping.get(join_type, "outer")


def _infer_type(series: pd.Series) -> str:
    """Infiere el tipo semantico de una columna para advertencias."""
    non_null = series.dropna()
    if non_null.empty:
        return "vacio"

    # Intentar convertir a numero.
    numeric_count = pd.to_numeric(non_null, errors="coerce").notna().sum()
    if numeric_count / len(non_null) > 0.8:
        return "numero"

    # Intentar convertir a fecha.
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
