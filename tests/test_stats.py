"""
tests/test_stats.py — Tests unitarios de engine/stats.py.

No requieren PySide6. Cubren RNF-STATS-03 (testabilidad sin GUI).

Tests incluidos (>= 15):
  1.  df vacio: StatsResult con 0 filas y lista de columnas vacia.
  2.  df vacio con columnas: columnas presentes, 0 filas.
  3.  df numerico simple: suma, promedio, min, max correctos.
  4.  df numerico con nulos: nulos excluidos del calculo.
  5.  df con columna de fecha (datetime nativo).
  6.  df con columna de fecha como texto (dd/mm/yyyy).
  7.  df con columna de texto: dtype_label = "texto".
  8.  df con columna mixta (>20% no-numerica): se trata como texto, no numero.
  9.  df con columna 100% nula: null_pct = 100.0, unique_count = 0.
  10. matched_rows None: campo se propaga tal cual.
  11. matched_rows provisto: se propaga correctamente.
  12. columna identificadora (cuil): dtype_label = "identificador", is_identifier = True.
  13. columna identificadora (dni): excluida de stats numericas.
  14. df con una sola fila: stats sin error.
  15. df con una sola columna: stats sin error.
  16. columna de nombre con tildes y ene: nombre preservado.
  17. columna de nombre vacio (string vacio): sin error.
  18. idempotencia: llamar dos veces produce mismo resultado.
  19. total_cols correcto con multiples columnas.
  20. num_effective refleja valores no-nulos usados en el calculo.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from engine.stats import compute_stats, StatsResult, ColumnStats, _is_identifier_column


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_col(result: StatsResult, name: str) -> ColumnStats:
    """Obtiene el ColumnStats por nombre. Falla si no existe."""
    for cs in result.columns:
        if cs.name == name:
            return cs
    raise KeyError(f"Columna '{name}' no encontrada en StatsResult")


# ---------------------------------------------------------------------------
# Test 1: DataFrame vacio (0 filas, 0 columnas)
# ---------------------------------------------------------------------------

def test_df_vacio_sin_columnas():
    df = pd.DataFrame()
    result = compute_stats(df)
    assert result.total_rows == 0
    assert result.total_cols == 0
    assert result.columns == []
    assert isinstance(result.duration_ms, float)


# ---------------------------------------------------------------------------
# Test 2: DataFrame vacio con columnas definidas
# ---------------------------------------------------------------------------

def test_df_vacio_con_columnas():
    df = pd.DataFrame(columns=["col_a", "col_b", "col_c"])
    result = compute_stats(df)
    assert result.total_rows == 0
    assert result.total_cols == 3
    assert len(result.columns) == 3
    col_a = _get_col(result, "col_a")
    assert col_a.null_count == 0
    assert col_a.unique_count == 0


# ---------------------------------------------------------------------------
# Test 3: DataFrame numerico simple, sin nulos
# ---------------------------------------------------------------------------

def test_df_numerico_simple():
    df = pd.DataFrame({"importe": [100.0, 200.0, 300.0, 400.0]})
    result = compute_stats(df)
    cs = _get_col(result, "importe")
    assert cs.dtype_label == "numero"
    assert cs.null_count == 0
    assert cs.null_pct == 0.0
    assert cs.unique_count == 4
    assert cs.num_sum == pytest.approx(1000.0)
    assert cs.num_mean == pytest.approx(250.0)
    assert cs.num_min == pytest.approx(100.0)
    assert cs.num_max == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# Test 4: DataFrame numerico con nulos — nulos excluidos del calculo
# ---------------------------------------------------------------------------

def test_df_numerico_con_nulos():
    df = pd.DataFrame({"importe_prima": [1500.0, 2300.0, None, 800.0, 1200.0]})
    result = compute_stats(df)
    cs = _get_col(result, "importe_prima")
    assert cs.dtype_label == "numero"
    assert cs.null_count == 1
    assert cs.null_pct == pytest.approx(20.0)
    assert cs.num_sum == pytest.approx(5800.0)
    assert cs.num_mean == pytest.approx(1450.0)
    assert cs.num_min == pytest.approx(800.0)
    assert cs.num_max == pytest.approx(2300.0)
    assert cs.num_effective == 4


# ---------------------------------------------------------------------------
# Test 5: Columna de fecha nativa (datetime)
# ---------------------------------------------------------------------------

def test_df_columna_fecha_nativa():
    df = pd.DataFrame({
        "fecha": pd.to_datetime(["2023-11-30", "2024-03-01", "2025-01-10", None])
    })
    result = compute_stats(df)
    cs = _get_col(result, "fecha")
    assert cs.dtype_label == "fecha"
    assert cs.null_count == 1
    assert cs.date_min == "30/11/2023"
    assert cs.date_max == "10/01/2025"
    assert cs.num_sum is None


# ---------------------------------------------------------------------------
# Test 6: Columna de fecha como texto (dd/mm/yyyy)
# ---------------------------------------------------------------------------

def test_df_columna_fecha_texto():
    df = pd.DataFrame({
        "fecha_baja": ["01/08/2026", "15/07/2026", "01/09/2026"]
    })
    result = compute_stats(df)
    cs = _get_col(result, "fecha_baja")
    assert cs.dtype_label == "fecha"
    assert cs.date_min == "15/07/2026"
    assert cs.date_max == "01/09/2026"


# ---------------------------------------------------------------------------
# Test 7: Columna de texto
# ---------------------------------------------------------------------------

def test_df_columna_texto():
    df = pd.DataFrame({
        "estado": ["activo", "cancelado", "suspendido", "activo", "activo"]
    })
    result = compute_stats(df)
    cs = _get_col(result, "estado")
    assert cs.dtype_label == "texto"
    assert cs.null_count == 0
    assert cs.unique_count == 3
    assert cs.num_sum is None
    assert cs.date_min is None


# ---------------------------------------------------------------------------
# Test 8: Columna mixta (texto con algunos numeros, < 80% numericos)
# ---------------------------------------------------------------------------

def test_df_columna_mixta_no_numerica():
    # 3 de 5 no son numericos => 40% numerico => se trata como texto
    df = pd.DataFrame({
        "campo": ["123", "abc", "456", "def", "ghi"]
    })
    result = compute_stats(df)
    cs = _get_col(result, "campo")
    # 2/5 = 40% numericos, no supera el 80%; debe ser texto
    assert cs.dtype_label == "texto"
    assert cs.num_sum is None


# ---------------------------------------------------------------------------
# Test 9: Columna 100% nula
# ---------------------------------------------------------------------------

def test_df_columna_100_nula():
    df = pd.DataFrame({
        "fecha_fallecimiento_renaper": [None, None, None, None, None]
    })
    result = compute_stats(df)
    cs = _get_col(result, "fecha_fallecimiento_renaper")
    assert cs.null_count == 5
    assert cs.null_pct == pytest.approx(100.0)
    assert cs.unique_count == 0
    assert cs.date_min is None
    assert cs.date_max is None
    assert cs.num_sum is None


# ---------------------------------------------------------------------------
# Test 10: matched_rows None se propaga
# ---------------------------------------------------------------------------

def test_matched_rows_none():
    df = pd.DataFrame({"col": [1, 2, 3]})
    result = compute_stats(df, matched_rows=None, left_only_rows=None, right_only_rows=None)
    assert result.matched_rows is None
    assert result.left_only_rows is None
    assert result.right_only_rows is None


# ---------------------------------------------------------------------------
# Test 11: matched_rows provisto se propaga correctamente
# ---------------------------------------------------------------------------

def test_matched_rows_provisto():
    df = pd.DataFrame({"col": [1, 2, 3, 4, 5]})
    result = compute_stats(df, matched_rows=3, left_only_rows=1, right_only_rows=1)
    assert result.matched_rows == 3
    assert result.left_only_rows == 1
    assert result.right_only_rows == 1
    assert result.total_rows == 5


# ---------------------------------------------------------------------------
# Test 12: Columna identificadora por nombre (cuil)
# ---------------------------------------------------------------------------

def test_columna_identificadora_cuil():
    df = pd.DataFrame({
        "cuil_numero": [20301234567, 27401234568, 23501234569]
    })
    result = compute_stats(df)
    cs = _get_col(result, "cuil_numero")
    assert cs.dtype_label == "identificador"
    assert cs.is_identifier is True
    assert cs.num_sum is None
    assert cs.num_mean is None


# ---------------------------------------------------------------------------
# Test 13: Columna identificadora por nombre (dni)
# ---------------------------------------------------------------------------

def test_columna_identificadora_dni():
    df = pd.DataFrame({
        "dni": [12345678, 23456789, 34567890]
    })
    result = compute_stats(df)
    cs = _get_col(result, "dni")
    assert cs.dtype_label == "identificador"
    assert cs.is_identifier is True
    assert cs.num_sum is None


# ---------------------------------------------------------------------------
# Test 14: DataFrame con una sola fila
# ---------------------------------------------------------------------------

def test_df_una_sola_fila():
    df = pd.DataFrame({"importe": [500.0], "nombre": ["juan"]})
    result = compute_stats(df)
    assert result.total_rows == 1
    cs_imp = _get_col(result, "importe")
    assert cs_imp.num_sum == pytest.approx(500.0)
    assert cs_imp.num_min == pytest.approx(500.0)
    assert cs_imp.num_max == pytest.approx(500.0)
    cs_nom = _get_col(result, "nombre")
    assert cs_nom.unique_count == 1


# ---------------------------------------------------------------------------
# Test 15: DataFrame con una sola columna
# ---------------------------------------------------------------------------

def test_df_una_sola_columna():
    df = pd.DataFrame({"unica": ["a", "b", "a", "b", "a"]})
    result = compute_stats(df)
    assert result.total_cols == 1
    assert len(result.columns) == 1
    cs = result.columns[0]
    assert cs.name == "unica"
    assert cs.unique_count == 2   # "a" y "b"


# ---------------------------------------------------------------------------
# Test 16: Nombre de columna con tildes y ene
# ---------------------------------------------------------------------------

def test_nombre_columna_con_tildes():
    df = pd.DataFrame({"Razon social": ["empresa a", "empresa b"]})
    result = compute_stats(df)
    cs = _get_col(result, "Razon social")
    assert cs.name == "Razon social"
    assert cs.dtype_label == "texto"


# ---------------------------------------------------------------------------
# Test 17: Nombre de columna vacio (string vacio)
# ---------------------------------------------------------------------------

def test_nombre_columna_vacio():
    df = pd.DataFrame({"": ["x", "y", "z"]})
    result = compute_stats(df)
    assert len(result.columns) == 1
    cs = result.columns[0]
    assert cs.name == ""
    assert cs.dtype_label == "texto"


# ---------------------------------------------------------------------------
# Test 18: Idempotencia — mismos resultados en dos llamadas
# ---------------------------------------------------------------------------

def test_idempotencia():
    df = pd.DataFrame({
        "importe": [100.0, 200.0, None],
        "fecha": ["01/01/2025", "15/06/2025", "31/12/2025"],
        "estado": ["activo", "cancelado", "activo"],
    })
    r1 = compute_stats(df, matched_rows=2, left_only_rows=1, right_only_rows=0)
    r2 = compute_stats(df, matched_rows=2, left_only_rows=1, right_only_rows=0)

    assert r1.total_rows == r2.total_rows
    assert r1.total_cols == r2.total_cols
    assert r1.matched_rows == r2.matched_rows

    for cs1, cs2 in zip(r1.columns, r2.columns):
        assert cs1.name == cs2.name
        assert cs1.dtype_label == cs2.dtype_label
        assert cs1.null_count == cs2.null_count
        assert cs1.unique_count == cs2.unique_count
        if cs1.num_sum is not None:
            assert cs1.num_sum == pytest.approx(cs2.num_sum)


# ---------------------------------------------------------------------------
# Test 19: total_cols correcto con multiples columnas
# ---------------------------------------------------------------------------

def test_total_cols_multiple():
    df = pd.DataFrame({
        "a": [1], "b": [2], "c": [3], "d": [4], "e": [5],
        "f": [6], "g": [7],
    })
    result = compute_stats(df)
    assert result.total_cols == 7
    assert len(result.columns) == 7


# ---------------------------------------------------------------------------
# Test 20: num_effective refleja cantidad de valores no-nulos en calculo
# ---------------------------------------------------------------------------

def test_num_effective():
    df = pd.DataFrame({
        "saldo": [100.0, None, 200.0, None, None, 300.0]
    })
    result = compute_stats(df)
    cs = _get_col(result, "saldo")
    assert cs.dtype_label == "numero"
    assert cs.null_count == 3
    assert cs.num_effective == 3
    assert cs.num_sum == pytest.approx(600.0)
    assert cs.num_mean == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Test adicional: importe cero e importe negativo (CA-STATS-005-02)
# ---------------------------------------------------------------------------

def test_importe_cero_y_negativo():
    df = pd.DataFrame({
        "importe_cobrado": [0.0, -150.5, 200.0]
    })
    result = compute_stats(df)
    cs = _get_col(result, "importe_cobrado")
    assert cs.dtype_label == "numero"
    assert cs.num_sum == pytest.approx(49.5)
    assert cs.num_min == pytest.approx(-150.5)
    assert cs.num_max == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Test adicional: funcion _is_identifier_column
# ---------------------------------------------------------------------------

def test_is_identifier_column_positivos():
    assert _is_identifier_column("cuil_beneficiario") is True
    assert _is_identifier_column("CUIL") is True
    assert _is_identifier_column("nro_poliza") is True
    assert _is_identifier_column("codigo_cuenta") is True
    assert _is_identifier_column("expediente_id") is True


def test_is_identifier_column_negativos():
    assert _is_identifier_column("importe") is False
    assert _is_identifier_column("estado") is False
    assert _is_identifier_column("fecha_baja") is False
    assert _is_identifier_column("nombre_producto") is False
