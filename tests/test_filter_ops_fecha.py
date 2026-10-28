"""
tests/test_filter_ops_fecha.py — Pruebas de los nuevos operadores de fecha
en engine/filter_ops.py.

Cubre: fecha_antes_de, fecha_despues_de, fecha_entre.
Datos sinteticos exclusivamente.
"""
from __future__ import annotations

import pandas as pd
import pytest

from engine.filter_ops import FilterCondition, apply_filters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def df_fechas() -> pd.DataFrame:
    """DataFrame con columna de fechas en formato argentino (sintetico)."""
    return pd.DataFrame({
        "fecha": [
            "01/01/2024",
            "15/06/2024",
            "31/12/2024",
            "01/01/2025",
            "15/06/2025",
        ],
        "codigo": ["A", "B", "C", "D", "E"],
    })


def df_fechas_iso() -> pd.DataFrame:
    """DataFrame con fechas en formato ISO 8601."""
    return pd.DataFrame({
        "fecha": [
            "2024-01-01",
            "2024-06-15",
            "2024-12-31",
            "2025-01-01",
            "2025-06-15",
        ],
        "codigo": ["A", "B", "C", "D", "E"],
    })


def df_fechas_mixtas() -> pd.DataFrame:
    """DataFrame con mezcla de fechas validas e invalidas."""
    return pd.DataFrame({
        "fecha": [
            "01/01/2024",
            "no-es-fecha",
            "15/06/2024",
            "",
            "31/12/2024",
        ],
        "codigo": ["A", "B", "C", "D", "E"],
    })


# ---------------------------------------------------------------------------
# Tests fecha_antes_de
# ---------------------------------------------------------------------------

class TestFechaAntesDe:
    def test_filtra_fechas_menores_o_iguales(self):
        """fecha_antes_de 15/06/2024: devuelve filas <= 15/06/2024."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_antes_de", value="15/06/2024")
        result = apply_filters(df, [cond])
        # 01/01/2024 y 15/06/2024 (inclusive)
        assert len(result) == 2
        assert set(result["codigo"]) == {"A", "B"}

    def test_inclusivo_incluye_la_fecha_limite(self):
        """fecha_antes_de es inclusivo: la fecha exacta se incluye."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_antes_de", value="31/12/2024")
        result = apply_filters(df, [cond])
        # A, B, C (31/12/2024 incluido)
        assert "C" in result["codigo"].values

    def test_todas_antes(self):
        """Si todas las fechas son anteriores al limite, se devuelven todas."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_antes_de", value="01/01/2026")
        result = apply_filters(df, [cond])
        assert len(result) == 5

    def test_ninguna_antes(self):
        """Si ninguna fecha es anterior al limite, se devuelven cero filas."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_antes_de", value="01/01/2023")
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_formato_iso_en_columna(self):
        """Funciona con fechas en formato ISO en la columna."""
        df = df_fechas_iso()
        cond = FilterCondition(column="fecha", operator="fecha_antes_de", value="2024-06-15")
        result = apply_filters(df, [cond])
        assert len(result) == 2
        assert set(result["codigo"]) == {"A", "B"}

    def test_valor_invalido_devuelve_cero_filas(self):
        """Si value no parsea como fecha, devuelve 0 filas (conservador)."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_antes_de", value="no-es-fecha")
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_valor_vacio_devuelve_cero_filas(self):
        """value vacio no parsea como fecha: devuelve 0 filas."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_antes_de", value="")
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_celdas_no_parseables_se_excluyen(self):
        """Celdas que no parsean como fecha no aparecen en el resultado."""
        df = df_fechas_mixtas()
        cond = FilterCondition(column="fecha", operator="fecha_antes_de", value="31/12/2024")
        result = apply_filters(df, [cond])
        # Solo A, C, E tienen fechas validas y <= 31/12/2024
        assert "no-es-fecha" not in result["fecha"].values
        assert "" not in result["fecha"].values


# ---------------------------------------------------------------------------
# Tests fecha_despues_de
# ---------------------------------------------------------------------------

class TestFechaDespuesDe:
    def test_filtra_fechas_mayores_o_iguales(self):
        """fecha_despues_de 15/06/2024: devuelve filas >= 15/06/2024."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_despues_de", value="15/06/2024")
        result = apply_filters(df, [cond])
        # 15/06/2024 (inclusive), 31/12/2024, 01/01/2025, 15/06/2025
        assert len(result) == 4
        assert "B" in result["codigo"].values  # 15/06/2024 incluido

    def test_inclusivo_incluye_la_fecha_limite(self):
        """fecha_despues_de es inclusivo: la fecha exacta se incluye."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_despues_de", value="01/01/2024")
        result = apply_filters(df, [cond])
        assert "A" in result["codigo"].values
        assert len(result) == 5

    def test_ninguna_despues(self):
        """Si ninguna fecha es posterior al limite, se devuelven cero filas."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_despues_de", value="01/01/2026")
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_valor_invalido_devuelve_cero_filas(self):
        """value invalido devuelve 0 filas."""
        df = df_fechas()
        cond = FilterCondition(column="fecha", operator="fecha_despues_de", value="texto")
        result = apply_filters(df, [cond])
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests fecha_entre
# ---------------------------------------------------------------------------

class TestFechaEntre:
    def test_filtra_rango_inclusivo(self):
        """fecha_entre incluye ambos extremos."""
        df = df_fechas()
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="15/06/2024",
            value2="01/01/2025",
        )
        result = apply_filters(df, [cond])
        # B (15/06/2024), C (31/12/2024), D (01/01/2025)
        assert len(result) == 3
        assert set(result["codigo"]) == {"B", "C", "D"}

    def test_rango_de_un_dia(self):
        """Rango con desde == hasta devuelve solo la fecha exacta."""
        df = df_fechas()
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="15/06/2024",
            value2="15/06/2024",
        )
        result = apply_filters(df, [cond])
        assert len(result) == 1
        assert result.iloc[0]["codigo"] == "B"

    def test_rango_completo_devuelve_todo(self):
        """Rango que abarca todas las fechas devuelve todas las filas."""
        df = df_fechas()
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="01/01/2023",
            value2="31/12/2026",
        )
        result = apply_filters(df, [cond])
        assert len(result) == 5

    def test_rango_sin_filas(self):
        """Rango entre dos fechas que no contienen ninguna fila devuelve 0."""
        df = df_fechas()
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="01/02/2024",
            value2="01/05/2024",
        )
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_value2_invalido_devuelve_cero(self):
        """Si value2 no parsea como fecha, devuelve 0 filas."""
        df = df_fechas()
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="01/01/2024",
            value2="no-parseable",
        )
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_value_invalido_devuelve_cero(self):
        """Si value no parsea como fecha, devuelve 0 filas."""
        df = df_fechas()
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="no-parseable",
            value2="31/12/2025",
        )
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_celdas_no_parseables_excluidas(self):
        """Celdas con valores no parseables como fecha no aparecen en el resultado."""
        df = df_fechas_mixtas()
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="01/01/2024",
            value2="31/12/2024",
        )
        result = apply_filters(df, [cond])
        for v in result["fecha"]:
            assert v not in ("no-es-fecha", "")

    def test_df_vacio_no_crash(self):
        """DataFrame vacio no crashea con fecha_entre."""
        df = pd.DataFrame({"fecha": [], "codigo": []})
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="01/01/2024",
            value2="31/12/2024",
        )
        result = apply_filters(df, [cond])
        assert result.empty


# ---------------------------------------------------------------------------
# Tests de integracion con condiciones combinadas
# ---------------------------------------------------------------------------

class TestFechaConOtrasCondiciones:
    def test_fecha_y_contiene_combinados(self):
        """Filtro de fecha combinado con 'contiene' en otra columna (AND)."""
        df = pd.DataFrame({
            "fecha": ["01/01/2024", "15/06/2024", "31/12/2024", "01/01/2025"],
            "tipo":  ["credito", "debito", "credito", "credito"],
        })
        cond_fecha = FilterCondition(
            column="fecha", operator="fecha_antes_de", value="30/06/2024"
        )
        cond_tipo = FilterCondition(
            column="tipo", operator="contiene", value="credito"
        )
        result = apply_filters(df, [cond_fecha, cond_tipo])
        # Solo 01/01/2024 (credito, antes de 30/06/2024)
        assert len(result) == 1
        assert result.iloc[0]["tipo"] == "credito"

    def test_fecha_con_quick_search(self):
        """Filtro de fecha + quick_search combinados."""
        df = pd.DataFrame({
            "fecha": ["01/01/2024", "15/06/2024", "31/12/2024"],
            "ref":   ["REF001", "REF002", "REF003"],
        })
        cond = FilterCondition(
            column="fecha", operator="fecha_despues_de", value="01/06/2024"
        )
        result = apply_filters(df, [cond], quick_search="REF002")
        assert len(result) == 1
        assert result.iloc[0]["ref"] == "REF002"

    def test_columna_inexistente_devuelve_cero(self):
        """Operador de fecha sobre columna inexistente devuelve 0 filas."""
        df = df_fechas()
        cond = FilterCondition(
            column="columna_inexistente",
            operator="fecha_antes_de",
            value="01/01/2025",
        )
        result = apply_filters(df, [cond])
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests de FilterCondition con nuevos operadores
# ---------------------------------------------------------------------------

class TestFilterConditionFecha:
    def test_fecha_antes_de_es_valido(self):
        """FilterCondition acepta fecha_antes_de sin lanzar."""
        cond = FilterCondition(column="f", operator="fecha_antes_de", value="01/01/2025")
        assert cond.operator == "fecha_antes_de"

    def test_fecha_despues_de_es_valido(self):
        """FilterCondition acepta fecha_despues_de sin lanzar."""
        cond = FilterCondition(column="f", operator="fecha_despues_de", value="01/01/2025")
        assert cond.operator == "fecha_despues_de"

    def test_fecha_entre_es_valido(self):
        """FilterCondition acepta fecha_entre con value y value2."""
        cond = FilterCondition(
            column="f",
            operator="fecha_entre",
            value="01/01/2024",
            value2="31/12/2024",
        )
        assert cond.operator == "fecha_entre"
        assert cond.value2 == "31/12/2024"

    def test_value2_default_es_cadena_vacia(self):
        """value2 tiene valor por defecto cadena vacia."""
        cond = FilterCondition(column="f", operator="contiene", value="x")
        assert cond.value2 == ""
