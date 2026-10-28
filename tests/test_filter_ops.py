"""
tests/test_filter_ops.py — Pruebas de engine/filter_ops.py.

Cubre todos los operadores de FilterCondition, apply_filters, casos limite
y propiedades (idempotencia, conmutatividad de condiciones AND).
No importa nada de PySide6.
"""
from __future__ import annotations

import pandas as pd
import pytest

from engine.filter_ops import OPERADORES_VALIDOS, FilterCondition, apply_filters


# ---------------------------------------------------------------------------
# Helpers de construccion de DataFrames sinteticos
# ---------------------------------------------------------------------------

def df_nombres() -> pd.DataFrame:
    """DataFrame con columna de nombres ficticios."""
    return pd.DataFrame({
        "nombre": ["GARCIA JUAN", "PEREZ ANA", "LOPEZ CARLOS", "GARCIA ROSA"],
        "estado": ["activo", "inactivo", "activo", "activo"],
    })


def df_importes() -> pd.DataFrame:
    """DataFrame con importes numericos ficticios."""
    return pd.DataFrame({
        "codigo": ["C001", "C002", "C003", "C004"],
        "importe": [100.0, 200.0, 300.0, 0.0],
    })


def df_con_nulos() -> pd.DataFrame:
    """DataFrame con valores None y cadenas vacias."""
    return pd.DataFrame({
        "campo": [None, "", "  ", "valor", "otro"],
        "id": [1, 2, 3, 4, 5],
    })


def df_cuils() -> pd.DataFrame:
    """DataFrame con CUILs ficticios (formato XX-XXXXXXXX-X)."""
    return pd.DataFrame({
        "cuil": ["20-11111111-1", "20-22222222-2", "27-33333333-3", "otro"],
        "tipo": ["fisica", "fisica", "juridica", "desconocido"],
    })


# ---------------------------------------------------------------------------
# Tests de quick_search
# ---------------------------------------------------------------------------

class TestQuickSearch:
    def test_quick_search_case_insensitive(self):
        """Buscar 'garcia' debe encontrar filas con 'GARCIA'."""
        df = df_nombres()
        result = apply_filters(df, [], quick_search="garcia")
        assert len(result) == 2
        assert all("GARCIA" in n for n in result["nombre"])

    def test_quick_search_vacio(self):
        """Sin texto de busqueda rapida se devuelven todas las filas."""
        df = df_nombres()
        result = apply_filters(df, [], quick_search="")
        assert len(result) == len(df)

    def test_quick_search_solo_espacios(self):
        """Cadena de solo espacios equivale a sin busqueda."""
        df = df_nombres()
        result = apply_filters(df, [], quick_search="   ")
        assert len(result) == len(df)

    def test_quick_search_busca_en_todas_las_columnas(self):
        """La busqueda rapida recorre todas las columnas del DataFrame."""
        df = df_nombres()
        # "inactivo" esta en la columna "estado", no en "nombre"
        result = apply_filters(df, [], quick_search="inactivo")
        assert len(result) == 1
        assert result.iloc[0]["estado"] == "inactivo"

    def test_quick_search_sin_resultados(self):
        """Busqueda que no matchea ninguna fila devuelve DataFrame vacio."""
        df = df_nombres()
        result = apply_filters(df, [], quick_search="xyzzy_no_existe")
        assert len(result) == 0

    def test_quick_search_con_tildes(self):
        """Busqueda con caracteres especiales/tildes no crashea."""
        df = pd.DataFrame({"nombre": ["JOSE GARCIA", "MARIA LOPEZ"]})
        result = apply_filters(df, [], quick_search="jose")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Tests por operador
# ---------------------------------------------------------------------------

class TestOperadorContiene:
    def test_contiene_match(self):
        """Operador 'contiene': valor parcial matchea."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="contiene", value="GARCIA")
        result = apply_filters(df, [cond])
        assert len(result) == 2

    def test_contiene_case_insensitive(self):
        """Operador 'contiene' es case-insensitive."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="contiene", value="garcia")
        result = apply_filters(df, [cond])
        assert len(result) == 2

    def test_contiene_no_match(self):
        """'contiene' con valor que no aparece en ninguna fila devuelve 0."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="contiene", value="ZZZNOMATCH")
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_contiene_valor_vacio_devuelve_todo(self):
        """Operador 'contiene' con valor vacio no filtra ninguna fila."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="contiene", value="")
        result = apply_filters(df, [cond])
        assert len(result) == len(df)


class TestOperadorIgualA:
    def test_igual_a_match_exacto(self):
        """Operador 'igual_a': solo la fila con valor exacto (case-insensitive)."""
        df = df_cuils()
        cond = FilterCondition(column="cuil", operator="igual_a", value="20-11111111-1")
        result = apply_filters(df, [cond])
        assert len(result) == 1
        assert result.iloc[0]["cuil"] == "20-11111111-1"

    def test_igual_a_no_match(self):
        """'igual_a' con valor que no existe devuelve 0 filas."""
        df = df_cuils()
        cond = FilterCondition(column="cuil", operator="igual_a", value="99-99999999-9")
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_igual_a_case_insensitive(self):
        """'igual_a' compara en minusculas en ambos lados."""
        df = pd.DataFrame({"tipo": ["FISICA", "JURIDICA"]})
        cond = FilterCondition(column="tipo", operator="igual_a", value="fisica")
        result = apply_filters(df, [cond])
        assert len(result) == 1


class TestOperadorEmpiezaCon:
    def test_empieza_con_match(self):
        """'empieza_con': prefijo presente matchea."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="empieza_con", value="GARC")
        result = apply_filters(df, [cond])
        assert len(result) == 2

    def test_empieza_con_no_match(self):
        """'empieza_con': prefijo ausente no matchea."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="empieza_con", value="ZZZZZ")
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_empieza_con_case_insensitive(self):
        """'empieza_con' es case-insensitive."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="empieza_con", value="garc")
        result = apply_filters(df, [cond])
        assert len(result) == 2


class TestOperadorMayorQue:
    def test_mayor_que_numerico(self):
        """'mayor_que' sobre columna numerica filtra correctamente."""
        df = df_importes()
        cond = FilterCondition(column="importe", operator="mayor_que", value="150")
        result = apply_filters(df, [cond])
        # 200 y 300 son > 150; 100 y 0 no lo son
        assert set(result["importe"]) == {200.0, 300.0}

    def test_mayor_que_no_incluye_igual(self):
        """'mayor_que' estricto: no incluye el umbral."""
        df = df_importes()
        cond = FilterCondition(column="importe", operator="mayor_que", value="100")
        result = apply_filters(df, [cond])
        assert 100.0 not in result["importe"].values

    def test_mayor_que_no_numerico(self):
        """'mayor_que' sobre columna de texto devuelve mascara False (no crash)."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="mayor_que", value="150")
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_mayor_que_valor_no_parseable(self):
        """'mayor_que' con valor no parseable como float devuelve 0 filas (no crash)."""
        df = df_importes()
        cond = FilterCondition(column="importe", operator="mayor_que", value="abc")
        result = apply_filters(df, [cond])
        assert len(result) == 0


class TestOperadorMenorQue:
    def test_menor_que_numerico(self):
        """'menor_que' sobre columna numerica filtra correctamente."""
        df = df_importes()
        cond = FilterCondition(column="importe", operator="menor_que", value="150")
        result = apply_filters(df, [cond])
        # 100 y 0 son < 150
        assert set(result["importe"]) == {100.0, 0.0}

    def test_menor_que_no_incluye_igual(self):
        """'menor_que' estricto: no incluye el umbral."""
        df = df_importes()
        cond = FilterCondition(column="importe", operator="menor_que", value="200")
        result = apply_filters(df, [cond])
        assert 200.0 not in result["importe"].values

    def test_menor_que_no_numerico(self):
        """'menor_que' sobre columna de texto devuelve mascara False (no crash)."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="menor_que", value="150")
        result = apply_filters(df, [cond])
        assert len(result) == 0


class TestOperadorEsVacio:
    def test_es_vacio_detecta_none_y_cadena_vacia(self):
        """'es_vacio' matchea None y cadena vacia."""
        df = df_con_nulos()
        cond = FilterCondition(column="campo", operator="es_vacio", value="")
        result = apply_filters(df, [cond])
        # None, "" y "  " deben matchear (3 filas)
        assert len(result) == 3

    def test_es_vacio_no_matchea_valor_presente(self):
        """'es_vacio' NO matchea filas con contenido real."""
        df = df_con_nulos()
        cond = FilterCondition(column="campo", operator="es_vacio", value="")
        result = apply_filters(df, [cond])
        assert "valor" not in result["campo"].values
        assert "otro" not in result["campo"].values


class TestOperadorNoEsVacio:
    def test_no_es_vacio_inverso_de_es_vacio(self):
        """'no_es_vacio' devuelve exactamente las filas que 'es_vacio' no devolveria."""
        df = df_con_nulos()
        cond_vacio = FilterCondition(column="campo", operator="es_vacio", value="")
        cond_no_vacio = FilterCondition(column="campo", operator="no_es_vacio", value="")
        vacios = apply_filters(df, [cond_vacio])
        no_vacios = apply_filters(df, [cond_no_vacio])
        assert len(vacios) + len(no_vacios) == len(df)
        assert set(vacios.index).isdisjoint(set(no_vacios.index))

    def test_no_es_vacio_matchea_valor_presente(self):
        """'no_es_vacio' incluye filas con contenido."""
        df = df_con_nulos()
        cond = FilterCondition(column="campo", operator="no_es_vacio", value="")
        result = apply_filters(df, [cond])
        assert "valor" in result["campo"].values
        assert "otro" in result["campo"].values


# ---------------------------------------------------------------------------
# Tests de multiples condiciones (AND)
# ---------------------------------------------------------------------------

class TestMultiplesCondiciones:
    def test_multiples_condiciones_and(self):
        """Dos condiciones se combinan como AND: interseccion de resultados."""
        df = df_nombres()
        cond1 = FilterCondition(column="nombre", operator="contiene", value="GARCIA")
        cond2 = FilterCondition(column="estado", operator="igual_a", value="activo")
        result = apply_filters(df, [cond1, cond2])
        # GARCIA JUAN (activo), GARCIA ROSA (activo) — PEREZ ANA (inactivo) queda fuera
        assert len(result) == 2
        assert all(r == "activo" for r in result["estado"])

    def test_condiciones_orden_no_cambia_resultado(self):
        """Propiedad: invertir el orden de las condiciones AND da el mismo resultado."""
        df = df_nombres()
        cond1 = FilterCondition(column="nombre", operator="contiene", value="GARCIA")
        cond2 = FilterCondition(column="estado", operator="igual_a", value="activo")
        r1 = apply_filters(df, [cond1, cond2])
        r2 = apply_filters(df, [cond2, cond1])
        assert set(r1.index) == set(r2.index)

    def test_idempotencia_aplicar_dos_veces(self):
        """Propiedad: aplicar los mismos filtros dos veces da el mismo resultado."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="contiene", value="GARCIA")
        r1 = apply_filters(df, [cond])
        r2 = apply_filters(df, [cond])
        assert list(r1.index) == list(r2.index)
        assert list(r1["nombre"]) == list(r2["nombre"])

    def test_quick_search_y_condicion_column_combinados(self):
        """Condicion de columna + quick_search se combinan como AND."""
        df = df_nombres()
        cond = FilterCondition(column="nombre", operator="contiene", value="GARCIA")
        # quick_search busca "activo" — GARCIA ROSA (activo) y GARCIA JUAN (activo) matchean
        result = apply_filters(df, [cond], quick_search="activo")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests de casos limite
# ---------------------------------------------------------------------------

class TestCasosLimite:
    def test_df_vacio_no_crash(self):
        """apply_filters sobre DataFrame vacio devuelve DataFrame vacio sin crash."""
        df = pd.DataFrame(columns=["nombre", "estado"])
        cond = FilterCondition(column="nombre", operator="contiene", value="test")
        result = apply_filters(df, [cond])
        assert result.empty
        assert list(result.columns) == ["nombre", "estado"]

    def test_columna_inexistente_devuelve_cero_filas(self):
        """Condicion con columna que no existe en el df devuelve 0 filas (no crash)."""
        df = df_nombres()
        cond = FilterCondition(column="columna_que_no_existe", operator="contiene", value="x")
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_operador_invalido_lanza_valueerror(self):
        """FilterCondition con operador no reconocido lanza ValueError."""
        with pytest.raises(ValueError, match="no reconocido"):
            FilterCondition(column="col", operator="operador_inventado", value="x")

    def test_operadores_validos_cubren_los_diez(self):
        """El conjunto OPERADORES_VALIDOS contiene exactamente los 10 operadores esperados
        (7 originales + 3 nuevos de fecha)."""
        esperados = {
            "contiene", "igual_a", "empieza_con",
            "mayor_que", "menor_que", "es_vacio", "no_es_vacio",
            "fecha_antes_de", "fecha_despues_de", "fecha_entre",
        }
        assert OPERADORES_VALIDOS == esperados

    def test_indices_preservados_tras_filtrado(self):
        """Los indices del DataFrame original se preservan en el resultado filtrado."""
        df = pd.DataFrame({"v": [10, 20, 30, 40]}, index=[100, 101, 102, 103])
        cond = FilterCondition(column="v", operator="mayor_que", value="15")
        result = apply_filters(df, [cond])
        assert list(result.index) == [101, 102, 103]

    def test_df_no_se_modifica(self):
        """apply_filters no muta el DataFrame de entrada."""
        df = df_nombres()
        original_len = len(df)
        original_cols = list(df.columns)
        cond = FilterCondition(column="nombre", operator="contiene", value="GARCIA")
        apply_filters(df, [cond])
        assert len(df) == original_len
        assert list(df.columns) == original_cols

    def test_sin_condiciones_devuelve_todo(self):
        """Sin condiciones y sin quick_search devuelve el DataFrame completo."""
        df = df_nombres()
        result = apply_filters(df, [])
        assert len(result) == len(df)

    def test_importe_cero_no_es_vacio(self):
        """Un importe 0 no debe considerarse 'vacio' por 'es_vacio'."""
        df = pd.DataFrame({"importe": [0, 0.0, 100.0]})
        cond = FilterCondition(column="importe", operator="es_vacio", value="")
        result = apply_filters(df, [cond])
        # 0 y 0.0 no son NaN ni cadena vacia: no deben matchear
        assert len(result) == 0

    def test_importe_negativo_mayor_que(self):
        """Importes negativos se comparan correctamente."""
        df = pd.DataFrame({"importe": [-100.0, -50.0, 0.0, 50.0]})
        cond = FilterCondition(column="importe", operator="mayor_que", value="-75")
        result = apply_filters(df, [cond])
        # -50, 0, 50 son > -75
        assert set(result["importe"]) == {-50.0, 0.0, 50.0}

    def test_valor_muy_largo_no_crash(self):
        """Valor de filtro muy largo (posible ataque) no crashea."""
        df = df_nombres()
        valor_largo = "A" * 10_000
        cond = FilterCondition(column="nombre", operator="contiene", value=valor_largo)
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_caracteres_especiales_en_valor(self):
        """Caracteres especiales/regex en valor de filtro no causan crash ni regex injection."""
        df = pd.DataFrame({"campo": ["precio (en USD)", "precio [descuento]", "otro"]})
        # Los parentesis y corchetes son metacaracteres de regex; regex=False los trata literalmente
        cond = FilterCondition(column="campo", operator="contiene", value="(en USD)")
        result = apply_filters(df, [cond])
        assert len(result) == 1

    def test_columna_con_mixto_numerico_y_texto(self):
        """Columna con mezcla de numeros y texto en mayor_que solo incluye los numericos validos."""
        df = pd.DataFrame({"val": ["100", "abc", "200", None, "300"]})
        cond = FilterCondition(column="val", operator="mayor_que", value="150")
        result = apply_filters(df, [cond])
        # Solo 200 y 300 son numericos y > 150
        assert set(result["val"]) == {"200", "300"}
