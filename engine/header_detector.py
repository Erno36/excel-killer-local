"""Deteccion conservadora de encabezados en las primeras filas de una hoja."""
from __future__ import annotations

from datetime import date, datetime
from numbers import Number

import pandas as pd


MAX_HEADER_SCAN_ROWS = 20


def detect_header_rows(
    raw: pd.DataFrame,
    max_rows: int = MAX_HEADER_SCAN_ROWS,
) -> list[int]:
    """Devuelve indices 0-based de encabezados candidatos, mejor primero."""
    if raw.empty:
        return []

    candidates: list[tuple[float, int]] = []
    scan_limit = min(max_rows, len(raw))

    for row_index in range(scan_limit):
        row = raw.iloc[row_index].tolist()
        populated = [value for value in row if not _is_empty(value)]
        if not populated:
            continue

        text_count = sum(_is_text_label(value) for value in populated)
        if text_count == 0:
            continue

        labels = [_normalize_label(value) for value in populated]
        unique_ratio = len(set(labels)) / len(labels)
        following = raw.iloc[row_index + 1 : row_index + 6]
        occupied = 0
        consistency_values: list[float] = []

        for column_index, header_value in enumerate(row):
            if _is_empty(header_value) or column_index >= following.shape[1]:
                continue
            values = [
                value for value in following.iloc[:, column_index].tolist()
                if not _is_empty(value)
            ]
            occupied += len(values)
            kinds = [_value_kind(value) for value in values]
            if kinds:
                most_common = max(kinds.count(kind) for kind in set(kinds))
                consistency_values.append(most_common / len(kinds))

        consistency = (
            sum(consistency_values) / len(consistency_values)
            if consistency_values
            else 0.0
        )
        occupancy = occupied / max(1, following.shape[0] * len(row))
        score = (
            text_count * 3.0
            + len(populated) * 0.25
            + unique_ratio
            + consistency * 2.0
            + occupancy
            - row_index * 0.01
        )
        candidates.append((score, row_index))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [row_index for _, row_index in candidates]


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_text_label(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    return bool(pd.isna(pd.to_numeric(text, errors="coerce")))


def _normalize_label(value: object) -> str:
    return " ".join(str(value).strip().lower().split())


def _value_kind(value: object) -> str:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return "fecha"
    if isinstance(value, Number) and not isinstance(value, bool):
        return "numero"
    text = str(value).strip()
    if not pd.isna(pd.to_numeric(text, errors="coerce")):
        return "numero"
    return "texto"
