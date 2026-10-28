"""
tests/test_rules_engine.py — Pruebas unitarias para engine/rules_engine.py.

Cubre:
  - apply_rule con if_then_else (AND/OR, todos los operadores de condicion)
  - apply_rule con formula (todos los operadores, formatos)
  - apply_rule con date_diff (dias/meses/anos, absolute)
  - apply_all_rules (encadenamiento, tolerancia a reglas mal configuradas)
  - preview_rule (retorno correcto, sin datos, error tolerante)
  - Casos borde: columna inexistente, division por cero, fecha invalida, rule_type invalido

Sin dependencias de PySide6.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from data.models import BusinessRule, RuleCondition
from engine.rules_engine import (
    CONDITION_OPERATORS,
    RULE_TYPES_VALIDOS,
    apply_all_rules,
    apply_rule,
    preview_rule,
)


# ---------------------------------------------------------------------------
# Fixtures de DataFrames sinteticos
# ---------------------------------------------------------------------------

@pytest.fixture
def df_simple() -> pd.DataFrame:
    return pd.DataFrame({
        "nombre": ["Ana", "Bruno", "Carla", "Diego", "Elena"],
        "estado": ["activo", "inactivo", "activo", "cancelado", "activo"],
        "importe": ["1500.00", "2300.00", "800.00", "1200.00", "3000.00"],
        "fecha_inicio": ["01/01/2025", "15/03/2024", "10/06/2023", "01/01/2026", "20/12/2025"],
        "fecha_fin":    ["31/12/2025", "30/06/2025", "09/06/2024", "31/03/2026", "19/12/2026"],
    })


@pytest.fixture
def df_numerico() -> pd.DataFrame:
    return pd.DataFrame({
        "precio": [100.0, 200.0, 300.0, 0.0],
        "cantidad": [2.0, 5.0, 0.0, 10.0],
        "descuento": [10.0, 50.0, 30.0, 5.0],
    })


@pytest.fixture
def df_con_vacios() -> pd.DataFrame:
    return pd.DataFrame({
        "col_a": ["valor", "", None, "otro", "  "],
        "col_b": [1, 2, 3, 4, 5],
    })


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

def test_rule_types_validos() -> None:
    assert "if_then_else" in RULE_TYPES_VALIDOS
    assert "formula" in RULE_TYPES_VALIDOS
    assert "date_diff" in RULE_TYPES_VALIDOS


def test_condition_operators() -> None:
    for op in ("==", "!=", "<", "<=", ">", ">=", "contiene", "es_vacio", "no_es_vacio"):
        assert op in CONDITION_OPERATORS


# ---------------------------------------------------------------------------
# apply_rule — if_then_else
# ---------------------------------------------------------------------------

class TestIfThenElse:

    def test_equal_condition(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="resultado",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "==", "value": "activo"}],
                "combinator": "AND",
                "value_true": "SI",
                "value_false": "NO",
            },
        )
        result = apply_rule(df_simple, rule)
        assert "resultado" in result.columns
        assert list(result["resultado"]) == ["SI", "NO", "SI", "NO", "SI"]

    def test_case_insensitive_comparison(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "==", "value": "ACTIVO"}],
                "combinator": "AND",
                "value_true": "X",
                "value_false": "Y",
            },
        )
        result = apply_rule(df_simple, rule)
        # "activo" == "ACTIVO" tras normalizar a lowercase
        assert list(result["res"]) == ["X", "Y", "X", "Y", "X"]

    def test_not_equal_condition(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "!=", "value": "activo"}],
                "combinator": "AND",
                "value_true": "INACTIVO_O_CANCELADO",
                "value_false": "ACTIVO",
            },
        )
        result = apply_rule(df_simple, rule)
        assert result["res"].iloc[0] == "ACTIVO"
        assert result["res"].iloc[1] == "INACTIVO_O_CANCELADO"

    def test_contiene_operator(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="tiene_a",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "nombre", "operator": "contiene", "value": "a"}],
                "combinator": "AND",
                "value_true": "1",
                "value_false": "0",
            },
        )
        result = apply_rule(df_simple, rule)
        # Ana=1, Bruno=0, Carla=1, Diego=0, Elena=1
        assert list(result["tiene_a"]) == ["1", "0", "1", "0", "1"]

    def test_es_vacio_operator(self, df_con_vacios: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="vacio",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "col_a", "operator": "es_vacio", "value": ""}],
                "combinator": "AND",
                "value_true": "VACIO",
                "value_false": "CON_VALOR",
            },
        )
        result = apply_rule(df_con_vacios, rule)
        expected = ["CON_VALOR", "VACIO", "VACIO", "CON_VALOR", "VACIO"]
        assert list(result["vacio"]) == expected

    def test_no_es_vacio_operator(self, df_con_vacios: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="tiene_valor",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "col_a", "operator": "no_es_vacio", "value": ""}],
                "combinator": "AND",
                "value_true": "SI",
                "value_false": "NO",
            },
        )
        result = apply_rule(df_con_vacios, rule)
        assert list(result["tiene_valor"]) == ["SI", "NO", "NO", "SI", "NO"]

    def test_numeric_comparison_mayor(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="caro",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "precio", "operator": ">", "value": "150"}],
                "combinator": "AND",
                "value_true": "CARO",
                "value_false": "BARATO",
            },
        )
        result = apply_rule(df_numerico, rule)
        # 100>150=F, 200>150=T, 300>150=T, 0>150=F
        assert list(result["caro"]) == ["BARATO", "CARO", "CARO", "BARATO"]

    def test_numeric_comparison_menor_igual(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "precio", "operator": "<=", "value": "100"}],
                "combinator": "AND",
                "value_true": "X",
                "value_false": "Y",
            },
        )
        result = apply_rule(df_numerico, rule)
        assert list(result["res"]) == ["X", "Y", "Y", "X"]

    def test_combinator_or(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [
                    {"column": "estado", "operator": "==", "value": "activo"},
                    {"column": "estado", "operator": "==", "value": "inactivo"},
                ],
                "combinator": "OR",
                "value_true": "ACTIVO_O_INACTIVO",
                "value_false": "OTRO",
            },
        )
        result = apply_rule(df_simple, rule)
        # activo, inactivo, activo, cancelado, activo
        assert list(result["res"]) == [
            "ACTIVO_O_INACTIVO",
            "ACTIVO_O_INACTIVO",
            "ACTIVO_O_INACTIVO",
            "OTRO",
            "ACTIVO_O_INACTIVO",
        ]

    def test_combinator_and_multiple(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [
                    {"column": "estado", "operator": "==", "value": "activo"},
                    {"column": "nombre", "operator": "contiene", "value": "a"},
                ],
                "combinator": "AND",
                "value_true": "MATCH",
                "value_false": "NO",
            },
        )
        result = apply_rule(df_simple, rule)
        # Ana+activo=MATCH, Bruno+inactivo=NO, Carla+activo=MATCH, Diego+cancelado=NO, Elena+activo=MATCH
        assert list(result["res"]) == ["MATCH", "NO", "MATCH", "NO", "MATCH"]

    def test_column_not_in_df_returns_false_mask(self, df_simple: pd.DataFrame) -> None:
        """Columna inexistente en condicion -> todos False -> todos value_false."""
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "columna_inexistente", "operator": "==", "value": "X"}],
                "combinator": "AND",
                "value_true": "SI",
                "value_false": "NO",
            },
        )
        result = apply_rule(df_simple, rule)
        assert list(result["res"]) == ["NO"] * len(df_simple)

    def test_missing_conditions_raises(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={"conditions": [], "combinator": "AND", "value_true": "A", "value_false": "B"},
        )
        with pytest.raises(ValueError, match="if_then_else requiere"):
            apply_rule(df_simple, rule)

    def test_output_column_is_added_to_df(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="nueva_columna",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "==", "value": "activo"}],
                "combinator": "AND",
                "value_true": "A",
                "value_false": "B",
            },
        )
        result = apply_rule(df_simple, rule)
        assert "nueva_columna" in result.columns
        # Original no modificado
        assert "nueva_columna" not in df_simple.columns

    def test_output_column_replaces_existing(self, df_simple: pd.DataFrame) -> None:
        """Si output_column ya existe, se reemplaza."""
        rule = BusinessRule.new(
            output_column="estado",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "nombre", "operator": "==", "value": "Ana"}],
                "combinator": "AND",
                "value_true": "ANA",
                "value_false": "OTRO",
            },
        )
        result = apply_rule(df_simple, rule)
        assert result["estado"].iloc[0] == "ANA"
        assert result["estado"].iloc[1] == "OTRO"


# ---------------------------------------------------------------------------
# apply_rule — formula
# ---------------------------------------------------------------------------

class TestFormula:

    def test_suma_columnas(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="total",
            rule_type="formula",
            params={
                "left": "precio",
                "operator": "+",
                "right": "cantidad",
                "format": "number",
            },
        )
        result = apply_rule(df_numerico, rule)
        assert list(result["total"]) == [102.0, 205.0, 300.0, 10.0]

    def test_resta_columnas(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="neto",
            rule_type="formula",
            params={
                "left": "precio",
                "operator": "-",
                "right": "descuento",
                "format": "number",
            },
        )
        result = apply_rule(df_numerico, rule)
        assert list(result["neto"]) == [90.0, 150.0, 270.0, -5.0]

    def test_multiplicacion_columnas(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="subtotal",
            rule_type="formula",
            params={
                "left": "precio",
                "operator": "*",
                "right": "cantidad",
                "format": "number",
            },
        )
        result = apply_rule(df_numerico, rule)
        assert list(result["subtotal"]) == [200.0, 1000.0, 0.0, 0.0]

    def test_division_columnas(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="ratio",
            rule_type="formula",
            params={
                "left": "precio",
                "operator": "/",
                "right": "cantidad",
                "format": "number",
            },
        )
        result = apply_rule(df_numerico, rule)
        # 100/2=50, 200/5=40, 300/0=NaN, 0/10=0
        assert result["ratio"].iloc[0] == 50.0
        assert result["ratio"].iloc[1] == 40.0
        assert math.isnan(result["ratio"].iloc[2])
        assert result["ratio"].iloc[3] == 0.0

    def test_division_por_cero_literal(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="formula",
            params={
                "left": "precio",
                "operator": "/",
                "right": "0",
                "format": "number",
            },
        )
        result = apply_rule(df_numerico, rule)
        # Todos NaN por division por cero literal
        for val in result["res"]:
            assert math.isnan(val) or val is None or (isinstance(val, float) and math.isnan(val))

    def test_operando_literal_numerico(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="con_iva",
            rule_type="formula",
            params={
                "left": "precio",
                "operator": "*",
                "right": "1.21",
                "format": "number",
            },
        )
        result = apply_rule(df_numerico, rule)
        assert abs(result["con_iva"].iloc[0] - 121.0) < 0.01
        assert abs(result["con_iva"].iloc[1] - 242.0) < 0.01

    def test_formato_text(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="total_txt",
            rule_type="formula",
            params={
                "left": "precio",
                "operator": "+",
                "right": "descuento",
                "format": "text",
            },
        )
        result = apply_rule(df_numerico, rule)
        # Deben ser strings con 2 decimales
        assert result["total_txt"].iloc[0] == "110.00"
        assert result["total_txt"].iloc[1] == "250.00"
        assert isinstance(result["total_txt"].iloc[0], str)

    def test_operando_no_numerico_ni_columna_raises(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="formula",
            params={
                "left": "precio",
                "operator": "+",
                "right": "texto_invalido",
                "format": "number",
            },
        )
        with pytest.raises(ValueError, match="no es una columna"):
            apply_rule(df_numerico, rule)

    def test_missing_left_raises(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="formula",
            params={"left": "", "operator": "+", "right": "precio", "format": "number"},
        )
        with pytest.raises(ValueError, match="left"):
            apply_rule(df_numerico, rule)

    def test_operador_invalido_raises(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="formula",
            params={"left": "precio", "operator": "**", "right": "cantidad", "format": "number"},
        )
        with pytest.raises(ValueError, match="operador de formula"):
            apply_rule(df_numerico, rule)


# ---------------------------------------------------------------------------
# apply_rule — date_diff
# ---------------------------------------------------------------------------

class TestDateDiff:

    def test_diff_days(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="dias",
            rule_type="date_diff",
            params={
                "col_a": "fecha_fin",
                "col_b": "fecha_inicio",
                "unit": "days",
                "absolute": False,
            },
        )
        result = apply_rule(df_simple, rule)
        # Ana: 31/12/2025 - 01/01/2025 = 364 dias
        assert result["dias"].iloc[0] == 364

    def test_diff_months(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="meses",
            rule_type="date_diff",
            params={
                "col_a": "fecha_fin",
                "col_b": "fecha_inicio",
                "unit": "months",
                "absolute": False,
            },
        )
        result = apply_rule(df_simple, rule)
        # Ana: 364 // 30 = 12
        assert result["meses"].iloc[0] == 12

    def test_diff_years(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="anhos",
            rule_type="date_diff",
            params={
                "col_a": "fecha_fin",
                "col_b": "fecha_inicio",
                "unit": "years",
                "absolute": False,
            },
        )
        result = apply_rule(df_simple, rule)
        # Ana: 364 // 365 = 0
        assert result["anhos"].iloc[0] == 0

    def test_diff_negative_absolute_false(self, df_simple: pd.DataFrame) -> None:
        """Cuando col_a < col_b, el resultado es negativo."""
        rule = BusinessRule.new(
            output_column="dias_neg",
            rule_type="date_diff",
            params={
                "col_a": "fecha_inicio",
                "col_b": "fecha_fin",
                "unit": "days",
                "absolute": False,
            },
        )
        result = apply_rule(df_simple, rule)
        assert result["dias_neg"].iloc[0] < 0

    def test_diff_absolute_true(self, df_simple: pd.DataFrame) -> None:
        """Con absolute=True, el resultado es siempre >= 0."""
        rule = BusinessRule.new(
            output_column="dias_abs",
            rule_type="date_diff",
            params={
                "col_a": "fecha_inicio",
                "col_b": "fecha_fin",
                "unit": "days",
                "absolute": True,
            },
        )
        result = apply_rule(df_simple, rule)
        for val in result["dias_abs"]:
            assert math.isnan(val) or val >= 0

    def test_invalid_date_returns_nan(self) -> None:
        df = pd.DataFrame({
            "fecha_a": ["01/01/2025", "no_es_fecha", "31/12/2025"],
            "fecha_b": ["01/01/2024", "01/01/2024", "01/01/2025"],
        })
        rule = BusinessRule.new(
            output_column="dias",
            rule_type="date_diff",
            params={"col_a": "fecha_a", "col_b": "fecha_b", "unit": "days", "absolute": False},
        )
        result = apply_rule(df, rule)
        # 01/01/2025 - 01/01/2024 = 366 dias (2024 es bisiesto)
        assert result["dias"].iloc[0] == 366
        assert math.isnan(result["dias"].iloc[1])
        # 31/12/2025 - 01/01/2025 = 364 dias
        assert result["dias"].iloc[2] == 364

    def test_missing_col_a_raises(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="dias",
            rule_type="date_diff",
            params={"col_a": "", "col_b": "fecha_inicio", "unit": "days", "absolute": False},
        )
        with pytest.raises(ValueError, match="col_a"):
            apply_rule(df_simple, rule)

    def test_col_not_in_df_raises(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="dias",
            rule_type="date_diff",
            params={
                "col_a": "columna_inexistente",
                "col_b": "fecha_inicio",
                "unit": "days",
                "absolute": False,
            },
        )
        with pytest.raises(ValueError, match="no existe"):
            apply_rule(df_simple, rule)


# ---------------------------------------------------------------------------
# apply_rule — casos generales
# ---------------------------------------------------------------------------

class TestApplyRuleGeneral:

    def test_invalid_rule_type_raises(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="tipo_invalido",
        )
        with pytest.raises(ValueError, match="rule_type"):
            apply_rule(df_simple, rule)

    def test_original_df_not_modified(self, df_simple: pd.DataFrame) -> None:
        original_cols = list(df_simple.columns)
        rule = BusinessRule.new(
            output_column="nueva",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "==", "value": "activo"}],
                "combinator": "AND",
                "value_true": "A",
                "value_false": "B",
            },
        )
        apply_rule(df_simple, rule)
        assert list(df_simple.columns) == original_cols


# ---------------------------------------------------------------------------
# apply_all_rules
# ---------------------------------------------------------------------------

class TestApplyAllRules:

    def test_empty_rules_returns_same(self, df_simple: pd.DataFrame) -> None:
        result = apply_all_rules(df_simple, [])
        assert list(result.columns) == list(df_simple.columns)

    def test_chained_rules(self, df_simple: pd.DataFrame) -> None:
        rule1 = BusinessRule.new(
            output_column="grupo",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "==", "value": "activo"}],
                "combinator": "AND",
                "value_true": "A",
                "value_false": "B",
            },
        )
        rule2 = BusinessRule.new(
            output_column="grupo_completo",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "grupo", "operator": "==", "value": "A"}],
                "combinator": "AND",
                "value_true": "Grupo A activo",
                "value_false": "Grupo B",
            },
        )
        result = apply_all_rules(df_simple, [rule1, rule2])
        assert "grupo" in result.columns
        assert "grupo_completo" in result.columns
        assert result["grupo_completo"].iloc[0] == "Grupo A activo"
        assert result["grupo_completo"].iloc[1] == "Grupo B"

    def test_invalid_rule_skipped(self, df_simple: pd.DataFrame) -> None:
        """Una regla mal configurada se ignora; las demas se aplican igual."""
        rule_bad = BusinessRule.new(
            output_column="mala",
            rule_type="tipo_invalido",  # rule_type invalido -> ValueError -> ignorada
        )
        rule_good = BusinessRule.new(
            output_column="buena",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "==", "value": "activo"}],
                "combinator": "AND",
                "value_true": "OK",
                "value_false": "NO",
            },
        )
        result = apply_all_rules(df_simple, [rule_bad, rule_good])
        assert "mala" not in result.columns
        assert "buena" in result.columns

    def test_rules_applied_in_order(self, df_numerico: pd.DataFrame) -> None:
        """La segunda regla puede usar la columna creada por la primera."""
        rule1 = BusinessRule.new(
            output_column="suma",
            rule_type="formula",
            params={"left": "precio", "operator": "+", "right": "cantidad", "format": "number"},
        )
        rule2 = BusinessRule.new(
            output_column="suma_texto",
            rule_type="formula",
            params={"left": "suma", "operator": "+", "right": "0", "format": "text"},
        )
        result = apply_all_rules(df_numerico, [rule1, rule2])
        assert "suma" in result.columns
        assert "suma_texto" in result.columns
        assert result["suma_texto"].iloc[0] == "102.00"


# ---------------------------------------------------------------------------
# preview_rule
# ---------------------------------------------------------------------------

class TestPreviewRule:

    def test_returns_rows(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "==", "value": "activo"}],
                "combinator": "AND",
                "value_true": "SI",
                "value_false": "NO",
            },
        )
        rows = preview_rule(df_simple, rule, n=3)
        assert len(rows) == 3
        for resumen, valor in rows:
            assert isinstance(resumen, str)
            assert valor in ("SI", "NO")

    def test_respects_n_limit(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "==", "value": "activo"}],
                "combinator": "AND",
                "value_true": "A",
                "value_false": "B",
            },
        )
        rows = preview_rule(df_simple, rule, n=2)
        assert len(rows) == 2

    def test_invalid_rule_returns_empty(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="tipo_invalido",
        )
        rows = preview_rule(df_simple, rule, n=5)
        assert rows == []

    def test_empty_dataframe_returns_empty(self) -> None:
        df = pd.DataFrame({"col": []})
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "col", "operator": "==", "value": "x"}],
                "combinator": "AND",
                "value_true": "A",
                "value_false": "B",
            },
        )
        rows = preview_rule(df, rule, n=5)
        assert rows == []

    def test_resumen_includes_involved_columns(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="res",
            rule_type="if_then_else",
            params={
                "conditions": [{"column": "estado", "operator": "==", "value": "activo"}],
                "combinator": "AND",
                "value_true": "A",
                "value_false": "B",
            },
        )
        rows = preview_rule(df_simple, rule, n=1)
        resumen, _ = rows[0]
        # El resumen debe incluir el valor de la columna "estado"
        assert "activo" in resumen

    def test_formula_preview(self, df_numerico: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="suma",
            rule_type="formula",
            params={"left": "precio", "operator": "+", "right": "cantidad", "format": "text"},
        )
        rows = preview_rule(df_numerico, rule, n=2)
        assert len(rows) == 2
        _, valor = rows[0]
        assert valor == "102.00"

    def test_date_diff_preview(self, df_simple: pd.DataFrame) -> None:
        rule = BusinessRule.new(
            output_column="dias",
            rule_type="date_diff",
            params={
                "col_a": "fecha_fin",
                "col_b": "fecha_inicio",
                "unit": "days",
                "absolute": False,
            },
        )
        rows = preview_rule(df_simple, rule, n=1)
        assert len(rows) == 1
        _, valor = rows[0]
        assert valor == "364"


# ---------------------------------------------------------------------------
# BusinessRule.new — constructor de conveniencia
# ---------------------------------------------------------------------------

class TestBusinessRuleNew:

    def test_new_generates_uuid(self) -> None:
        r1 = BusinessRule.new("col", "formula")
        r2 = BusinessRule.new("col", "formula")
        assert r1.rule_id != r2.rule_id

    def test_new_defaults(self) -> None:
        r = BusinessRule.new("columna", "if_then_else")
        assert r.output_column == "columna"
        assert r.rule_type == "if_then_else"
        assert r.params == {}

    def test_new_with_params(self) -> None:
        params = {"conditions": [], "combinator": "AND", "value_true": "X", "value_false": "Y"}
        r = BusinessRule.new("col", "if_then_else", params)
        assert r.params == params
