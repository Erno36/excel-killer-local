"""
engine/cleansing.py — Motor de limpieza de datos (Data Cleansing).

Logica pura, sin dependencias de PySide6.
Todas las operaciones son no destructivas: retornan nuevas Series/FileEntry.

RESTRICCION: este modulo no registra valores de celdas (RN-019).
No lanza excepciones en normalize_date (celdas no parseables quedan sin cambio).
Si el patron de replace_regex es invalido, apply_rule lanza ValueError
y preview_rule retorna lista vacia.

Operaciones DataFrame-level (no aplican por serie):
  drop_column       — elimina una columna del archivo.
  filter_date_before — retiene filas donde la columna >= fecha (inclusive).
  filter_date_after  — retiene filas donde la columna <= fecha (inclusive).
  filter_date_range  — retiene filas donde desde <= columna <= hasta.
"""
from __future__ import annotations

import re
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING

import pandas as pd

from data.models import CleansingRule
from engine._date_utils import parse_date_flexible

if TYPE_CHECKING:
    from data.models import FileEntry

# ---------------------------------------------------------------------------
# Operaciones validas
# ---------------------------------------------------------------------------

OPERACIONES_VALIDAS: set[str] = {
    "strip_spaces",
    "to_uppercase",
    "to_lowercase",
    "capitalize",
    "replace_literal",
    "replace_regex",
    "remove_chars",
    "keep_only_digits",
    "normalize_date",
    "fill_empty",
    "pad_left",
    # Operaciones a nivel DataFrame (procesadas en apply_all_rules):
    "drop_column",
    "filter_date_before",
    "filter_date_after",
    "filter_date_range",
}

# Operaciones que actuan sobre el DataFrame completo y no sobre una serie.
# apply_rule no debe recibirlas; apply_all_rules las intercepta antes del bucle por serie.
_DF_LEVEL_OPS: frozenset[str] = frozenset({
    "drop_column",
    "filter_date_before",
    "filter_date_after",
    "filter_date_range",
})


# ---------------------------------------------------------------------------
# Aplicacion de una regla
# ---------------------------------------------------------------------------

def apply_rule(series: pd.Series, rule: CleansingRule) -> pd.Series:
    """
    Aplica UNA regla a la serie dada.
    Retorna una nueva pd.Series; no modifica la original.

    Lanza ValueError si:
    - la operacion no es valida
    - replace_regex tiene un pattern de regex invalido

    Lanza NotImplementedError si se intenta usar una operacion DataFrame-level
    (drop_column, filter_date_*) directamente sobre una serie. Estas operaciones
    deben ejecutarse via apply_all_rules.
    """
    op = rule.operation

    if op not in OPERACIONES_VALIDAS:
        raise ValueError(f"Operacion desconocida: '{op}'")

    if op in _DF_LEVEL_OPS:
        raise NotImplementedError(
            f"'{op}' opera a nivel DataFrame. Usar apply_all_rules en lugar de apply_rule."
        )

    # Trabajar con una copia string; NaN se convierte a "" para operaciones de texto
    # excepto fill_empty que necesita detectarlos antes.

    if op == "fill_empty":
        value = str(rule.params.get("value", ""))
        return series.fillna(value).replace("", value)

    if op == "strip_spaces":
        def _strip(v):
            if pd.isna(v):
                return v
            s = str(v).strip()
            # Colapsar espacios internos multiples en uno.
            s = re.sub(r" {2,}", " ", s)
            return s
        return series.apply(_strip)

    if op == "to_uppercase":
        return series.apply(lambda v: str(v).upper() if not pd.isna(v) else v)

    if op == "to_lowercase":
        return series.apply(lambda v: str(v).lower() if not pd.isna(v) else v)

    if op == "capitalize":
        return series.apply(lambda v: str(v).capitalize() if not pd.isna(v) else v)

    if op == "replace_literal":
        find = str(rule.params.get("find", ""))
        repl = str(rule.params.get("replace", ""))
        return series.apply(
            lambda v: str(v).replace(find, repl) if not pd.isna(v) else v
        )

    if op == "replace_regex":
        pattern = str(rule.params.get("pattern", ""))
        repl = str(rule.params.get("replace", ""))
        try:
            import warnings as _w
            with _w.catch_warnings():
                _w.simplefilter("ignore", FutureWarning)
                compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(
                f"Patron de expresion regular invalido: '{pattern}'. Detalle: {exc}"
            ) from exc
        return series.apply(
            lambda v: compiled.sub(repl, str(v)) if not pd.isna(v) else v
        )

    if op == "remove_chars":
        chars = str(rule.params.get("chars", ""))
        # Construir alternancia de caracteres escapados para eliminar.
        # Se usa alternancia (c1|c2|...) en lugar de clase de caracteres [...]
        # para evitar FutureWarning por sets anidados cuando chars contiene '[' o ']'.
        if not chars:
            return series.copy()
        pattern = "|".join(re.escape(c) for c in chars)
        compiled = re.compile(pattern)
        return series.apply(
            lambda v: compiled.sub("", str(v)) if not pd.isna(v) else v
        )

    if op == "keep_only_digits":
        return series.apply(
            lambda v: re.sub(r"[^0-9]", "", str(v)) if not pd.isna(v) else v
        )

    if op == "normalize_date":
        fmt_from = rule.params.get("format_from", "%d/%m/%Y")
        fmt_to = rule.params.get("format_to", "%Y-%m-%d")

        def _norm_date(v):
            if pd.isna(v):
                return v
            s = str(v).strip()
            try:
                from datetime import datetime as _dt
                return _dt.strptime(s, fmt_from).strftime(fmt_to)
            except (ValueError, TypeError):
                # Celdas que no parsean quedan sin cambio.
                return v

        return series.apply(_norm_date)

    if op == "pad_left":
        width = int(rule.params.get("width", 0))
        char = str(rule.params.get("char", "0"))
        if len(char) != 1:
            char = char[0] if char else "0"
        return series.apply(
            lambda v: str(v).zfill(width) if char == "0" and not pd.isna(v)
            else (str(v).rjust(width, char) if not pd.isna(v) else v)
        )

    # No deberia llegar aqui por la guarda al inicio.
    return series.copy()  # pragma: no cover


# ---------------------------------------------------------------------------
# Aplicacion de todas las reglas a la lista de FileEntry
# ---------------------------------------------------------------------------

def apply_all_rules(
    entries: list["FileEntry"],
    rules: list[CleansingRule],
    strict: bool = False,
) -> list["FileEntry"]:
    """
    Aplica TODAS las reglas al conjunto de FileEntry correspondientes por file_label.
    Retorna NUEVOS FileEntry (los originales no se modifican).
    Por compatibilidad, strict=False ignora reglas mal configuradas como antes.
    Con strict=True, una regla invalida o que falla detiene la operacion con
    ValueError para evitar presentar una limpieza parcial como completa.

    Orden de procesamiento:
    1. Operaciones DataFrame-level (drop_column, filter_date_*) en el orden
       en que aparecen en la lista de reglas.
    2. Operaciones por serie sobre cada columna, en el orden de la lista.
    """
    # Indexar entries por label para acceso O(1).
    entry_map: dict[str, "FileEntry"] = {e.label: e for e in entries}

    # Acumular DataFrames modificados en un dict separado.
    df_map: dict[str, pd.DataFrame] = {
        label: e.df.copy() for label, e in entry_map.items()
    }

    for rule in rules:
        if strict and not isinstance(rule.params, dict):
            raise ValueError("Una regla de limpieza tiene parametros invalidos.")
        label = rule.file_label
        if label not in entry_map:
            if strict:
                raise ValueError(f"La regla apunta a un archivo inexistente: '{label}'.")
            continue

        op = rule.operation
        col = rule.column

        # --- Operaciones a nivel DataFrame ---
        if op == "drop_column":
            if col in df_map[label].columns:
                df_map[label] = df_map[label].drop(columns=[col], errors="ignore")
            elif strict:
                raise ValueError(f"La columna '{col}' no existe en '{label}'.")
            continue

        if op in ("filter_date_before", "filter_date_after", "filter_date_range"):
            if col not in df_map[label].columns:
                if strict:
                    raise ValueError(f"La columna '{col}' no existe en '{label}'.")
                continue
            if strict:
                date_values = (
                    [rule.params.get("date", "")]
                    if op in ("filter_date_before", "filter_date_after")
                    else [
                        rule.params.get("date_from", ""),
                        rule.params.get("date_to", ""),
                    ]
                )
                parsed_dates = [parse_date_flexible(str(value)) for value in date_values]
                if any(value is None for value in parsed_dates):
                    raise ValueError(f"La regla de fechas para '{col}' tiene una fecha invalida.")
                if len(parsed_dates) == 2 and parsed_dates[0] > parsed_dates[1]:
                    raise ValueError(f"El rango de fechas para '{col}' esta invertido.")
                raw_dates = df_map[label][col]
                parsed_values = raw_dates.apply(
                    lambda value: (
                        parse_date_flexible(str(value)) if not pd.isna(value) else None
                    )
                )
                invalid_mask = (
                    raw_dates.notna()
                    & (raw_dates.astype(str).str.strip() != "")
                    & parsed_values.isna()
                )
                invalid_count = int(invalid_mask.sum())
                if invalid_count:
                    raise ValueError(
                        f"La columna '{col}' tiene {invalid_count} fechas no reconocidas; "
                        "corrigelas antes de filtrar."
                    )
            df_map[label] = _apply_date_filter(df_map[label], col, op, rule.params)
            continue

        # --- Operaciones por serie ---
        if col not in df_map[label].columns:
            if strict:
                raise ValueError(f"La columna '{col}' no existe en '{label}'.")
            continue
        try:
            df_map[label][col] = apply_rule(df_map[label][col], rule)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            if strict:
                raise ValueError(
                    f"No se pudo aplicar '{op}' sobre '{label}.{col}'."
                ) from exc
            # Ignorar reglas que fallan al aplicar en bloque.
            continue

    # Construir nuevos FileEntry con los DataFrames modificados.
    result: list["FileEntry"] = []
    for entry in entries:
        if entry.label in df_map:
            new_df = df_map[entry.label]
            from dataclasses import fields as dc_fields
            # Actualizar tambien row_count en metadata.
            new_metadata = dc_replace(
                entry.metadata,
                row_count=len(new_df),
                column_names=list(new_df.columns),
            )
            result.append(dc_replace(entry, df=new_df, metadata=new_metadata))
        else:
            result.append(entry)

    return result


# ---------------------------------------------------------------------------
# Preview de una regla (primeras n filas no vacias)
# ---------------------------------------------------------------------------

def preview_rule(
    series: "pd.Series | None",
    rule: CleansingRule,
    n: int = 5,
) -> list[tuple[str, str]]:
    """
    Aplica la regla a las primeras n filas no vacias de la serie.
    Retorna lista de (valor_antes, valor_despues).
    Si el pattern de regex es invalido, retorna lista vacia (no lanza).

    Para operaciones DataFrame-level (drop_column, filter_date_*) retorna
    una tupla descriptiva en lugar de datos reales: la operacion no puede
    previsualizarse sobre una sola serie sin el DataFrame completo.
    """
    op = rule.operation

    # Operaciones DataFrame-level: retornar descripcion sintetica.
    if op == "drop_column":
        return [("(columna eliminada)", "")]

    if op in ("filter_date_before", "filter_date_after", "filter_date_range"):
        return [("(filas filtradas por fecha)", "")]

    # Tomar las primeras n filas no nulas y no vacias.
    mask = series.notna() & (series.astype(str).str.strip() != "")
    sample = series[mask].head(n)

    if sample.empty:
        return []

    try:
        result_series = apply_rule(sample, rule)
    except ValueError:
        return []

    pairs: list[tuple[str, str]] = []
    for before, after in zip(sample, result_series):
        pairs.append((str(before) if not pd.isna(before) else "",
                      str(after) if not pd.isna(after) else ""))
    return pairs


# ---------------------------------------------------------------------------
# Helper interno: filtros de fecha a nivel DataFrame
# ---------------------------------------------------------------------------

def _apply_date_filter(
    df: pd.DataFrame,
    column: str,
    op: str,
    params: dict,
) -> pd.DataFrame:
    """
    Aplica un filtro de fecha sobre el DataFrame completo.

    Retorna un nuevo DataFrame con las filas que cumplen la condicion.
    Filas donde la columna no parsea como fecha se EXCLUYEN (comportamiento
    conservador: si no se puede determinar la fecha, se descarta la fila).

    Parametros de params segun operacion:
        filter_date_before: {"date": "dd/mm/aaaa"}   — retiene filas <= date
        filter_date_after:  {"date": "dd/mm/aaaa"}   — retiene filas >= date
        filter_date_range:  {"date_from": "...", "date_to": "..."}
    """
    col_series = df[column]

    # Parsear cada celda de la columna.
    parsed = col_series.apply(
        lambda v: parse_date_flexible(str(v)) if not pd.isna(v) else None
    )
    # Mascara de filas parseables.
    parseable_mask = parsed.notna()

    if op == "filter_date_before":
        threshold_str = str(params.get("date", ""))
        threshold = parse_date_flexible(threshold_str)
        if threshold is None:
            # Fecha invalida: no filtrar ninguna fila (conservador: retornar todas).
            return df.copy()
        mask = parseable_mask & (parsed <= threshold)

    elif op == "filter_date_after":
        threshold_str = str(params.get("date", ""))
        threshold = parse_date_flexible(threshold_str)
        if threshold is None:
            return df.copy()
        mask = parseable_mask & (parsed >= threshold)

    elif op == "filter_date_range":
        from_str = str(params.get("date_from", ""))
        to_str = str(params.get("date_to", ""))
        date_from = parse_date_flexible(from_str)
        date_to = parse_date_flexible(to_str)
        if date_from is None or date_to is None:
            return df.copy()
        mask = parseable_mask & (parsed >= date_from) & (parsed <= date_to)

    else:
        return df.copy()

    return df[mask].reset_index(drop=True)
