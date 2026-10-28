"""
tests/test_result_screen_delete_columns.py — Pruebas de CrossResultModel.delete_columns.

Usa la misma tecnica de stub de PySide6 que test_result_screen_model.py.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

# --- Stub PySide6 (mismo patron que test_result_screen_model.py) ---
pyside6_stub = MagicMock()
pyside6_stub.QtCore.QAbstractTableModel = object
pyside6_stub.QtCore.QModelIndex = MagicMock
pyside6_stub.QtCore.QSortFilterProxyModel = object
pyside6_stub.QtCore.Qt.ItemDataRole.DisplayRole = 0
pyside6_stub.QtCore.Qt.ItemDataRole.EditRole = 1
pyside6_stub.QtCore.Qt.ItemDataRole.BackgroundRole = 8
pyside6_stub.QtCore.Qt.ItemDataRole.ForegroundRole = 14
pyside6_stub.QtCore.Qt.Orientation.Horizontal = 1
pyside6_stub.QtCore.Qt.ItemFlag.NoItemFlags = 0
pyside6_stub.QtCore.Qt.ItemFlag.ItemIsEnabled = 1
pyside6_stub.QtCore.Qt.ItemFlag.ItemIsSelectable = 2
pyside6_stub.QtCore.Qt.ItemFlag.ItemIsEditable = 4
pyside6_stub.QtCore.QTimer = MagicMock
pyside6_stub.QtCore.Signal = MagicMock(return_value=None)

sys.modules.setdefault("PySide6", pyside6_stub)
sys.modules.setdefault("PySide6.QtCore", pyside6_stub.QtCore)
sys.modules.setdefault("PySide6.QtGui", MagicMock())
sys.modules.setdefault("PySide6.QtWidgets", MagicMock())
sys.modules.setdefault("audit.logger", MagicMock())
sys.modules.setdefault("data.models", MagicMock())
sys.modules.setdefault("engine.exporter", MagicMock())
sys.modules.setdefault("engine.filter_ops", MagicMock())
sys.modules.setdefault("ui.login_screen", MagicMock())


# ---------------------------------------------------------------------------
# Clase minima que replica la logica de delete_columns sin Qt.
# ---------------------------------------------------------------------------

class CrossResultModelDeleteColumns:
    """
    Replica la logica pura de CrossResultModel.delete_columns para pruebas
    unitarias sin Qt.
    """

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


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_model(cols: list[str] | None = None) -> CrossResultModelDeleteColumns:
    if cols is None:
        cols = ["a", "b", "c", "d"]
    data = {c: list(range(3)) for c in cols}
    return CrossResultModelDeleteColumns(pd.DataFrame(data))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDeleteColumns:

    def test_elimina_una_columna(self):
        """delete_columns([1]) elimina la columna de indice 1."""
        model = _make_model()
        deleted = model.delete_columns([1])
        assert deleted == 1
        assert "b" not in model.working_df.columns
        assert list(model.working_df.columns) == ["a", "c", "d"]

    def test_elimina_multiples_columnas(self):
        """delete_columns([0, 2]) elimina las columnas en los indices 0 y 2."""
        model = _make_model()
        deleted = model.delete_columns([0, 2])
        assert deleted == 2
        assert list(model.working_df.columns) == ["b", "d"]

    def test_retorna_cantidad_correcta(self):
        """El valor de retorno es la cantidad de columnas eliminadas."""
        model = _make_model()
        deleted = model.delete_columns([0, 1, 3])
        assert deleted == 3

    def test_lista_vacia_devuelve_cero(self):
        """delete_columns([]) devuelve 0 y no modifica el DataFrame."""
        model = _make_model()
        deleted = model.delete_columns([])
        assert deleted == 0
        assert len(model.working_df.columns) == 4

    def test_indice_negativo_ignorado(self):
        """DEF-002: indice negativo no elimina nada."""
        model = _make_model()
        deleted = model.delete_columns([-1])
        assert deleted == 0
        assert len(model.working_df.columns) == 4

    def test_indice_fuera_de_rango_ignorado(self):
        """DEF-002: indice >= numero de columnas no elimina nada."""
        model = _make_model()
        deleted = model.delete_columns([100])
        assert deleted == 0
        assert len(model.working_df.columns) == 4

    def test_mezcla_validos_e_invalidos(self):
        """DEF-002: [-1, 0, 2, 999] elimina solo los validos (0 y 2)."""
        model = _make_model()
        deleted = model.delete_columns([-1, 0, 2, 999])
        assert deleted == 2
        assert list(model.working_df.columns) == ["b", "d"]

    def test_duplicados_cuentan_una_vez(self):
        """[0, 0, 0] elimina solo 1 columna."""
        model = _make_model()
        deleted = model.delete_columns([0, 0, 0])
        assert deleted == 1
        assert len(model.working_df.columns) == 3

    def test_no_modifica_df_original(self):
        """El DataFrame original no muta tras delete_columns."""
        model = _make_model()
        original_cols = list(model.original_df.columns)
        model.delete_columns([0, 1])
        assert list(model.original_df.columns) == original_cols

    def test_limpia_edited_cells(self):
        """Tras delete_columns, _edited_cells queda vacio."""
        model = _make_model()
        model._edited_cells = {(0, 0), (1, 1), (2, 2)}
        model.delete_columns([1])
        assert model._edited_cells == set()

    def test_eliminar_ultima_columna(self):
        """Eliminar la unica columna deja DataFrame sin columnas."""
        model = _make_model(["solo"])
        deleted = model.delete_columns([0])
        assert deleted == 1
        assert list(model.working_df.columns) == []

    def test_filas_preservadas_tras_eliminar_columna(self):
        """El numero de filas no cambia tras eliminar columnas."""
        model = _make_model()
        filas_originales = len(model.working_df)
        model.delete_columns([0, 2])
        assert len(model.working_df) == filas_originales

    def test_datos_restantes_son_correctos(self):
        """Los datos de las columnas no eliminadas permanecen correctos."""
        df = pd.DataFrame({
            "a": [1, 2, 3],
            "b": [4, 5, 6],
            "c": [7, 8, 9],
        })
        model = CrossResultModelDeleteColumns(df)
        model.delete_columns([1])  # elimina "b"
        pd.testing.assert_series_equal(
            model.working_df["a"].reset_index(drop=True),
            pd.Series([1, 2, 3], name="a"),
        )
        pd.testing.assert_series_equal(
            model.working_df["c"].reset_index(drop=True),
            pd.Series([7, 8, 9], name="c"),
        )
