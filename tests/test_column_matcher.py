"""
tests/test_column_matcher.py — Tests unitarios para engine/column_matcher.py.
Sin dependencias de PySide6. Corre con pytest solo.
"""
from __future__ import annotations

import pandas as pd
import pytest

from engine.column_matcher import (
    _normalize_name,
    infer_column_type,
    suggest_pairs,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_lowercase(self):
        assert _normalize_name("CUIL") == "cuil"

    def test_strips_spaces(self):
        assert _normalize_name("  nombre  ") == "nombre"

    def test_removes_internal_spaces(self):
        assert _normalize_name("fecha baja") == "fechabaja"

    def test_removes_hyphens(self):
        assert _normalize_name("fecha-baja") == "fechabaja"

    def test_removes_underscores(self):
        assert _normalize_name("fecha_baja") == "fechabaja"

    def test_removes_dots(self):
        assert _normalize_name("fecha.baja") == "fechabaja"

    def test_removes_slashes(self):
        assert _normalize_name("fecha/baja") == "fechabaja"

    def test_combined(self):
        assert _normalize_name("  Apellido_Y Nombre  ") == "apellidoynombre"


# ---------------------------------------------------------------------------
# infer_column_type
# ---------------------------------------------------------------------------

class TestInferColumnType:
    def test_numeric_int_series(self):
        s = pd.Series([1, 2, 3, 4, 5])
        assert infer_column_type(s) == "numero"

    def test_numeric_float_series(self):
        s = pd.Series([1.1, 2.2, 3.3])
        assert infer_column_type(s) == "numero"

    def test_datetime_series(self):
        s = pd.Series(pd.to_datetime(["2026-01-01", "2026-06-15", "2026-10-26"]))
        assert infer_column_type(s) == "fecha"

    def test_text_dates_series(self):
        s = pd.Series(["01/01/2026", "15/06/2026", "26/10/2026"])
        assert infer_column_type(s) == "fecha"

    def test_text_series(self):
        s = pd.Series(["Seguro Vida", "Seguro Auto", "Seguro Hogar"])
        assert infer_column_type(s) == "texto"

    def test_empty_series_returns_texto(self):
        s = pd.Series([], dtype=object)
        assert infer_column_type(s) == "texto"

    def test_all_null_returns_texto(self):
        s = pd.Series([None, None, None])
        assert infer_column_type(s) == "texto"

    def test_mostly_numeric_text(self):
        # 9 de 10 son numericos -> "numero"
        s = pd.Series(["1", "2", "3", "4", "5", "6", "7", "8", "9", "abc"])
        assert infer_column_type(s) == "numero"

    def test_mixed_text_not_numeric(self):
        # Solo 1 de 5 es numerico -> no supera el umbral
        s = pd.Series(["abc", "def", "ghi", "jkl", "42"])
        assert infer_column_type(s) == "texto"

    def test_yyyymmdd_strings_classified_as_numero(self):
        """Strings YYYYMMDD se clasifican como numero (pd.to_numeric tiene prioridad sobre fechas)."""
        s = pd.Series(["20240101", "20240601", "20241026", "20230315"])
        assert infer_column_type(s) == "numero"

    def test_cuil_like_strings_classified_as_texto(self):
        """Strings con formato CUIL (20-XXXXXXXX-X) se clasifican como texto."""
        s = pd.Series(["20-12345678-9", "27-23456789-0", "20-34567890-1"])
        assert infer_column_type(s) == "texto"


# ---------------------------------------------------------------------------
# suggest_pairs
# ---------------------------------------------------------------------------

class TestSuggestPairs:
    def test_exact_match(self):
        left  = ["CUIL", "nombre", "estado"]
        right = ["CUIL", "fecha_baja", "motivo"]
        pairs = suggest_pairs(left, right)
        assert ("CUIL", "CUIL") in pairs

    def test_case_insensitive_match(self):
        left  = ["cuil", "nombre"]
        right = ["CUIL", "apellido"]
        pairs = suggest_pairs(left, right)
        assert ("cuil", "CUIL") in pairs

    def test_no_match_returns_empty(self):
        left  = ["precio", "cantidad"]
        right = ["fecha_alta", "motivo_baja"]
        pairs = suggest_pairs(left, right)
        assert pairs == []

    def test_no_duplicates_left(self):
        # La misma columna izquierda no debe aparecer dos veces
        left  = ["CUIL", "CUIL_2"]
        right = ["CUIL", "otro"]
        pairs = suggest_pairs(left, right)
        left_used = [p[0] for p in pairs]
        assert len(left_used) == len(set(left_used))

    def test_no_duplicates_right(self):
        # La misma columna derecha no debe aparecer dos veces
        left  = ["CUIL", "id"]
        right = ["CUIL", "CUIL"]  # duplicado inusual en datos reales
        pairs = suggest_pairs(left, right)
        right_used = [p[1] for p in pairs]
        assert len(right_used) == len(set(right_used))

    def test_containment_match(self):
        # "CUIL" esta contenido en "CUIL_PADRON"
        left  = ["CUIL"]
        right = ["CUIL_PADRON", "nombre"]
        pairs = suggest_pairs(left, right)
        assert ("CUIL", "CUIL_PADRON") in pairs

    def test_containment_reverse(self):
        # "CUIL_PADRON" contiene a "cuil" del lado derecho
        left  = ["CUIL_PADRON", "nombre"]
        right = ["cuil", "fecha"]
        pairs = suggest_pairs(left, right)
        assert ("CUIL_PADRON", "cuil") in pairs

    def test_exact_takes_priority_over_containment(self):
        # Existe un match exacto "fecha" y también contencion con "fecha_alta"
        left  = ["fecha", "nombre"]
        right = ["fecha", "fecha_alta"]
        pairs = suggest_pairs(left, right)
        # "fecha" debe matchear exacto con "fecha", no con "fecha_alta"
        fecha_pairs = [(l, r) for l, r in pairs if l == "fecha"]
        assert len(fecha_pairs) == 1
        assert fecha_pairs[0] == ("fecha", "fecha")

    def test_separator_normalization_match(self):
        # "fecha_baja" vs "fecha-baja" deben matchear
        left  = ["fecha_baja"]
        right = ["fecha-baja"]
        pairs = suggest_pairs(left, right)
        assert ("fecha_baja", "fecha-baja") in pairs

    def test_multiple_pairs_returned(self):
        left  = ["CUIL", "nombre", "estado"]
        right = ["CUIL", "nombre", "importe"]
        pairs = suggest_pairs(left, right)
        pair_set = set(pairs)
        assert ("CUIL", "CUIL") in pair_set
        assert ("nombre", "nombre") in pair_set

    def test_short_names_not_matched_by_containment(self):
        # Nombres con menos de 3 chars no deben matchear por contencion
        left  = ["id", "nombre"]
        right = ["identificador", "apellido"]
        pairs = suggest_pairs(left, right)
        # "id" tiene 2 chars -> no debe matchear "identificador" por contencion
        id_pairs = [(l, r) for l, r in pairs if l == "id"]
        assert id_pairs == []

    def test_empty_left(self):
        assert suggest_pairs([], ["CUIL", "nombre"]) == []

    def test_empty_right(self):
        assert suggest_pairs(["CUIL", "nombre"], []) == []

    def test_both_empty(self):
        assert suggest_pairs([], []) == []


# ---------------------------------------------------------------------------
# Regresión de logging / privacidad (RN-019)
# ---------------------------------------------------------------------------

def test_infer_column_type_no_output_a_stdout_stderr(capsys):
    """
    V8-PDP-02: infer_column_type no debe emitir valores de celda
    a stdout ni stderr (RN-019 regresión de logging).
    """
    import pandas as pd
    from engine.column_matcher import infer_column_type

    # Series con datos sensibles (CUILes sintéticos y nombres)
    series_sensible = pd.Series([
        "20-12345678-9",
        "27-98765432-1",
        "30-11122233-4",
        "García Juan",
        "Rodríguez Ana",
    ])

    infer_column_type(series_sensible)

    captured = capsys.readouterr()
    assert captured.out == "", (
        f"infer_column_type emitió a stdout: {captured.out!r}"
    )
    assert captured.err == "", (
        f"infer_column_type emitió a stderr: {captured.err!r}"
    )
