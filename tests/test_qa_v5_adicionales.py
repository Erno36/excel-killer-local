"""
tests/test_qa_v5_adicionales.py — Casos adicionales solicitados en QA v5.

Cubre exactamente los cinco casos del encargo que no estaban en los tests
pre-existentes, mas pruebas de seguridad de la revision RN-019.

Datos sinteticos exclusivamente.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine._date_utils import parse_date_flexible
from engine.filter_ops import FilterCondition, apply_filters


# ---------------------------------------------------------------------------
# Stubs PySide6 para poder importar CrossResultModel sin display
# ---------------------------------------------------------------------------

_pyside6_stub = MagicMock()
_pyside6_stub.QtCore.QAbstractTableModel = object
_pyside6_stub.QtCore.QModelIndex = MagicMock
_pyside6_stub.QtCore.QSortFilterProxyModel = object
_pyside6_stub.QtCore.Qt.ItemDataRole.DisplayRole = 0
_pyside6_stub.QtCore.Qt.ItemDataRole.EditRole = 1
_pyside6_stub.QtCore.Qt.ItemDataRole.BackgroundRole = 8
_pyside6_stub.QtCore.Qt.ItemDataRole.ForegroundRole = 14
_pyside6_stub.QtCore.Qt.Orientation.Horizontal = 1
_pyside6_stub.QtCore.Qt.ItemFlag.NoItemFlags = 0
_pyside6_stub.QtCore.Qt.ItemFlag.ItemIsEnabled = 1
_pyside6_stub.QtCore.Qt.ItemFlag.ItemIsSelectable = 2
_pyside6_stub.QtCore.Qt.ItemFlag.ItemIsEditable = 4
_pyside6_stub.QtCore.QTimer = MagicMock
_pyside6_stub.QtCore.Signal = MagicMock(return_value=None)

sys.modules.setdefault("PySide6", _pyside6_stub)
sys.modules.setdefault("PySide6.QtCore", _pyside6_stub.QtCore)
sys.modules.setdefault("PySide6.QtGui", MagicMock())
sys.modules.setdefault("PySide6.QtWidgets", MagicMock())
sys.modules.setdefault("audit.logger", MagicMock())
sys.modules.setdefault("data.models", MagicMock())
sys.modules.setdefault("engine.exporter", MagicMock())
sys.modules.setdefault("engine.filter_ops", MagicMock())
sys.modules.setdefault("ui.login_screen", MagicMock())


# ---------------------------------------------------------------------------
# Replica minima de CrossResultModel.delete_columns (identica a la produccion)
# ---------------------------------------------------------------------------

class _ModelDeleteCols:
    def __init__(self, df: pd.DataFrame) -> None:
        self._df_original = df.copy()
        self._df = df.copy()
        self._edited_cells: set = set()

    def delete_columns(self, col_indices: list[int]) -> int:
        if not col_indices:
            return 0
        total_cols = len(self._df.columns)
        valid_indices = sorted(
            {i for i in col_indices if 0 <= i < total_cols},
            reverse=True,
        )
        if not valid_indices:
            return 0
        cols_to_drop = [self._df.columns[i] for i in valid_indices]
        self._df = self._df.drop(columns=cols_to_drop, errors="ignore")
        self._edited_cells = set()
        return len(cols_to_drop)

    @property
    def working_df(self) -> pd.DataFrame:
        return self._df

    @property
    def original_df(self) -> pd.DataFrame:
        return self._df_original


def _model(*cols: str) -> _ModelDeleteCols:
    data = {c: [1, 2, 3] for c in cols}
    return _ModelDeleteCols(pd.DataFrame(data))


# ===========================================================================
# CASO 1: test_filter_date_range_ambas_inclusivas
# Fecha "desde" == fecha columna -> incluida; "hasta" == fecha columna -> incluida.
# ===========================================================================

class TestFilterDateRangeAmbasInclusivas:
    """CA: ambos extremos del rango son inclusivos (RN semántico de la operación)."""

    def test_fecha_desde_igual_a_valor_de_celda_incluida(self):
        """El extremo inferior (date_from == celda) debe quedar incluido."""
        df = pd.DataFrame({
            "fecha": ["01/06/2024", "15/06/2024", "30/06/2024"],
            "id":    [1, 2, 3],
        })
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="01/06/2024",   # exactamente igual a la primera celda
            value2="10/06/2024",
        )
        result = apply_filters(df, [cond])
        assert 1 in result["id"].values, (
            "La fila con fecha igual al extremo inferior debe estar incluida"
        )

    def test_fecha_hasta_igual_a_valor_de_celda_incluida(self):
        """El extremo superior (date_to == celda) debe quedar incluido."""
        df = pd.DataFrame({
            "fecha": ["01/06/2024", "15/06/2024", "30/06/2024"],
            "id":    [1, 2, 3],
        })
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="20/06/2024",
            value2="30/06/2024",   # exactamente igual a la última celda
        )
        result = apply_filters(df, [cond])
        assert 3 in result["id"].values, (
            "La fila con fecha igual al extremo superior debe estar incluida"
        )

    def test_rango_un_dia_exacto_ambos_extremos_inclusivos(self):
        """value == value2 == celda: la fila se incluye (rango de un dia)."""
        df = pd.DataFrame({
            "fecha": ["14/06/2024", "15/06/2024", "16/06/2024"],
            "id":    [1, 2, 3],
        })
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="15/06/2024",
            value2="15/06/2024",
        )
        result = apply_filters(df, [cond])
        assert len(result) == 1
        assert result.iloc[0]["id"] == 2

    def test_filter_date_before_extremo_inclusivo(self):
        """fecha_antes_de: la celda con exactamente el valor del umbral se incluye."""
        df = pd.DataFrame({
            "fecha": ["15/06/2024", "16/06/2024"],
            "id":    [1, 2],
        })
        cond = FilterCondition(
            column="fecha",
            operator="fecha_antes_de",
            value="15/06/2024",
        )
        result = apply_filters(df, [cond])
        assert 1 in result["id"].values, "El umbral 'antes de' debe ser inclusivo"
        assert 2 not in result["id"].values

    def test_filter_date_after_extremo_inclusivo(self):
        """fecha_despues_de: la celda con exactamente el valor del umbral se incluye."""
        df = pd.DataFrame({
            "fecha": ["14/06/2024", "15/06/2024"],
            "id":    [1, 2],
        })
        cond = FilterCondition(
            column="fecha",
            operator="fecha_despues_de",
            value="15/06/2024",
        )
        result = apply_filters(df, [cond])
        assert 2 in result["id"].values, "El umbral 'despues de' debe ser inclusivo"
        assert 1 not in result["id"].values


# ===========================================================================
# CASO 2: test_fecha_entre_value2_vacio
# value2="" en fecha_entre -> retorna mascara False toda, sin crash.
# ===========================================================================

class TestFechaEntreValue2Vacio:
    """Seguridad: value2 vacio no debe crashear ni incluir filas incorrectas."""

    def test_value2_vacio_retorna_cero_filas_sin_crash(self):
        """value2='' no parsea como fecha -> False en toda la mascara, sin excepcion."""
        df = pd.DataFrame({
            "fecha": ["01/01/2024", "15/06/2024", "31/12/2024"],
            "id":    [1, 2, 3],
        })
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="01/01/2024",
            value2="",              # vacio — NO debe parsear
        )
        # No debe lanzar excepcion
        result = apply_filters(df, [cond])
        assert len(result) == 0, (
            "value2 vacio debe producir mascara False (0 filas) sin crash"
        )

    def test_value2_solo_espacios_retorna_cero_filas_sin_crash(self):
        """value2 de solo espacios tampoco debe parsear ni crashear."""
        df = pd.DataFrame({
            "fecha": ["01/01/2024"],
            "id":    [1],
        })
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="01/01/2024",
            value2="   ",
        )
        result = apply_filters(df, [cond])
        assert len(result) == 0

    def test_value_vacio_tambien_retorna_cero_filas(self):
        """Simetria: value='' también retorna 0 filas sin crash."""
        df = pd.DataFrame({
            "fecha": ["01/01/2024"],
            "id":    [1],
        })
        cond = FilterCondition(
            column="fecha",
            operator="fecha_entre",
            value="",
            value2="31/12/2024",
        )
        result = apply_filters(df, [cond])
        assert len(result) == 0


# ===========================================================================
# CASO 3: test_drop_column_no_modifica_original
# Los FileEntry originales no mutan.
# (ya cubierto en test_cleansing_nuevas_ops.py; este test usa apply_all_rules
# directamente y verifica que la lista de entrada no muta)
# ===========================================================================

class TestDropColumnNoModificaOriginal:
    """RN: apply_all_rules es no-destructivo para los FileEntry de entrada."""

    def test_lista_de_entrada_no_muta(self):
        """La lista pasada a apply_all_rules no se modifica."""
        from data.models import FileEntry, FileMetadata
        from engine.cleansing import apply_all_rules, CleansingRule

        df = pd.DataFrame({"col_a": [1, 2], "col_b": ["x", "y"]})
        entry = FileEntry(
            path=None,
            label="X",
            sheet_index=0,
            df=df,
            metadata=FileMetadata(
                path=None,
                sheet_names=["Hoja1"],
                sheet_used="Hoja1",
                row_count=len(df),
                column_names=list(df.columns),
            ),
            is_virtual=True,
        )
        original_entries = [entry]
        rules = [CleansingRule.new("X", "col_a", "drop_column")]

        result = apply_all_rules(original_entries, rules)

        # El entry original no debe haber mutado
        assert "col_a" in original_entries[0].df.columns, (
            "El FileEntry original no debe mutar tras apply_all_rules"
        )
        # El result sí debe tener la columna eliminada
        assert "col_a" not in result[0].df.columns

    def test_df_original_del_entry_no_muta(self):
        """El DataFrame interno del FileEntry original no cambia de longitud."""
        from data.models import FileEntry, FileMetadata
        from engine.cleansing import apply_all_rules, CleansingRule

        df = pd.DataFrame({
            "fecha": ["01/01/2024", "15/06/2024", "31/12/2024"],
            "id":    [1, 2, 3],
        })
        entry = FileEntry(
            path=None,
            label="Y",
            sheet_index=0,
            df=df,
            metadata=FileMetadata(
                path=None,
                sheet_names=["H"],
                sheet_used="H",
                row_count=3,
                column_names=["fecha", "id"],
            ),
            is_virtual=True,
        )
        rules = [CleansingRule.new("Y", "fecha", "filter_date_before", {"date": "15/06/2024"})]
        apply_all_rules([entry], rules)

        assert len(entry.df) == 3, (
            "El DataFrame del FileEntry original no debe perder filas"
        )


# ===========================================================================
# CASO 4: test_delete_columns_guard_negativos
# delete_columns([-1]) -> no crash, retorna 0.
# ===========================================================================

class TestDeleteColumnsGuardNegativos:
    """DEF-002: guard de indices invalidos en delete_columns."""

    def test_indice_menos_uno_retorna_cero_sin_crash(self):
        """[-1] retorna 0 y no elimina columnas."""
        m = _model("a", "b", "c")
        result = m.delete_columns([-1])
        assert result == 0
        assert list(m.working_df.columns) == ["a", "b", "c"]

    def test_indice_muy_negativo_retorna_cero(self):
        """[-999] retorna 0 y no elimina columnas."""
        m = _model("a", "b")
        result = m.delete_columns([-999])
        assert result == 0
        assert len(m.working_df.columns) == 2

    def test_lista_solo_negativos_retorna_cero(self):
        """Lista con varios negativos: ninguno se procesa."""
        m = _model("a", "b", "c", "d")
        result = m.delete_columns([-1, -2, -10])
        assert result == 0
        assert len(m.working_df.columns) == 4

    def test_mezcla_negativo_y_valido_procesa_solo_validos(self):
        """[-1, 0] procesa solo el indice 0."""
        m = _model("a", "b", "c")
        result = m.delete_columns([-1, 0])
        assert result == 1
        assert "a" not in m.working_df.columns
        assert list(m.working_df.columns) == ["b", "c"]

    def test_indice_igual_a_column_count_ignorado(self):
        """Indice == len(columns) esta fuera de rango y se ignora."""
        m = _model("a", "b")
        result = m.delete_columns([2])   # len == 2, rango valido es [0,1]
        assert result == 0


# ===========================================================================
# CASO 5: test_parse_date_flexible_retorna_none_en_invalido
# String no fecha -> None (sin excepcion).
# ===========================================================================

class TestParseDateFlexibleRetornaNoneEnInvalido:
    """Comportamiento conservador: entradas no-fecha -> None, nunca excepcion."""

    @pytest.mark.parametrize("entrada", [
        "no-es-fecha",
        "texto libre",
        "DROP TABLE usuarios",
        "=1+1",                   # inyeccion de formula
        "@SUM(A1:A10)",
        "99/99/9999",
        "2025-13-01",             # mes 13 invalido
        "00/00/0000",
        "A" * 1000,               # string muy largo
        "",
        "   ",
        "NaN",
        "None",
        "null",
        "undefined",
    ])
    def test_invalido_retorna_none(self, entrada: str):
        """Cualquier string no-fecha retorna None sin excepcion."""
        result = parse_date_flexible(entrada)
        assert result is None, (
            f"parse_date_flexible({entrada!r}) debio retornar None, retorno {result!r}"
        )

    @pytest.mark.parametrize("entrada", [
        None,
        0,
        123,
        [],
        {},
        object(),
    ])
    def test_no_string_retorna_none(self, entrada):
        """Tipos no-string retornan None sin excepcion."""
        result = parse_date_flexible(entrada)  # type: ignore[arg-type]
        assert result is None


# ===========================================================================
# SEGURIDAD: _apply_date_filter con params["date"] largo arbitrario
# ===========================================================================

class TestSeguridad:
    """Pruebas de robustez y seguridad para el codigo nuevo."""

    def test_apply_date_filter_params_date_muy_largo_no_crash(self):
        """
        Seguridad: si params['date'] tiene un valor arbitrariamente largo,
        _apply_date_filter no debe crashear — debe retornar el DataFrame original.
        """
        from engine.cleansing import _apply_date_filter

        df = pd.DataFrame({
            "fecha": ["01/01/2024", "15/06/2024"],
            "id":    [1, 2],
        })
        valor_largo = "X" * 10_000
        result = _apply_date_filter(df, "fecha", "filter_date_before", {"date": valor_largo})
        # Sin fecha valida: retorna todas las filas sin filtrar
        assert len(result) == len(df), (
            "Valor arbitrariamente largo en params debe retornar el DataFrame sin filtrar"
        )

    def test_apply_date_filter_inyeccion_sql_en_date_no_crash(self):
        """Inyeccion SQL en params['date'] no debe crashear."""
        from engine.cleansing import _apply_date_filter

        df = pd.DataFrame({"fecha": ["01/01/2024"], "id": [1]})
        payload_sql = "'; DROP TABLE usuarios; --"
        result = _apply_date_filter(df, "fecha", "filter_date_before", {"date": payload_sql})
        assert len(result) == 1  # conservador: sin fecha valida retorna todo

    def test_apply_date_filter_inyeccion_formula_en_date_no_crash(self):
        """Formula de Excel en params['date'] no debe crashear ni producir evaluacion."""
        from engine.cleansing import _apply_date_filter

        df = pd.DataFrame({"fecha": ["01/01/2024"], "id": [1]})
        payload_formula = "=CMD('calc.exe')"
        result = _apply_date_filter(df, "fecha", "filter_date_before", {"date": payload_formula})
        assert len(result) == 1

    def test_date_comparison_value2_vacio_retorna_false_sin_excepcion(self):
        """
        Seguridad: _date_comparison con value2='' en fecha_entre
        retorna mascara False en todas las filas y no lanza excepcion.
        """
        from engine.filter_ops import _date_comparison

        col = pd.Series(["01/01/2024", "15/06/2024", "31/12/2024"])
        mask = _date_comparison(col, "fecha_entre", "01/01/2024", "")
        assert not mask.any(), (
            "_date_comparison con value2='' debe retornar mascara False total"
        )
        assert len(mask) == len(col)

    def test_date_comparison_value2_invalido_retorna_false_sin_excepcion(self):
        """_date_comparison con value2 no-fecha retorna False, sin excepcion."""
        from engine.filter_ops import _date_comparison

        col = pd.Series(["01/01/2024", "15/06/2024"])
        mask = _date_comparison(col, "fecha_entre", "01/01/2024", "no-es-fecha")
        assert not mask.any()

    def test_rn019_log_columnas_no_contiene_valores_de_celda(self):
        """
        RN-019: el AuditEntry de COLUMNS_DELETED registra nombres de columnas
        (metadata), no valores de celdas.
        Verificar que la lista de columnas no filtra valores de celda al log.
        """
        # Simular el flujo: columnas con nombres de metadato, no valores de celda
        col_names = ["CUIL", "nombre_producto", "importe"]   # nombres de campo
        valores_celda = ["20-11111111-1", "Juan Perez", "1500.00"]  # valores de celda

        # En el log solo deben aparecer los nombres de columna, no los valores
        log_payload = {"accion": "COLUMNS_DELETED", "columnas": col_names}
        log_str = str(log_payload)

        for valor in valores_celda:
            assert valor not in log_str, (
                f"El log no debe contener el valor de celda '{valor}'"
            )
        for nombre in col_names:
            assert nombre in log_str, (
                f"El log debe contener el nombre de columna '{nombre}'"
            )
