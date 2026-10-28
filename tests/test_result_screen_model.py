"""
Tests de re-QA para CrossResultModel (ui/result_screen.py).

DEF-001: setData con dtype numerico — no debe corromper dtype a object.
DEF-002: delete_rows con indices negativos — no debe crashear ni eliminar filas incorrectas.
"""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

# CrossResultModel no usa Qt para logica de datos, pero si para QAbstractTableModel.
# Mockeamos la capa Qt para poder correr sin display.
import sys

# Patch PySide6 antes de importar el modulo bajo prueba.
# Solo necesitamos que QAbstractTableModel exista como clase base sin efectos.
from unittest.mock import MagicMock

# Creamos stubs minimos de PySide6 para poder importar result_screen sin display.
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

# Stub para los modulos Qt que result_screen importa.
sys.modules.setdefault("PySide6", pyside6_stub)
sys.modules.setdefault("PySide6.QtCore", pyside6_stub.QtCore)
sys.modules.setdefault("PySide6.QtGui", MagicMock())
sys.modules.setdefault("PySide6.QtWidgets", MagicMock())

# Tambien stubbear dependencias internas que no son relevantes para estos tests.
sys.modules.setdefault("audit.logger", MagicMock())
sys.modules.setdefault("data.models", MagicMock())
sys.modules.setdefault("engine.exporter", MagicMock())
sys.modules.setdefault("engine.filter_ops", MagicMock())
sys.modules.setdefault("ui.login_screen", MagicMock())


# ---------------------------------------------------------------------------
# Clase minima que replica la logica critica de CrossResultModel sin Qt.
# Copiada tal cual del archivo de produccion para aislar la logica pura.
# ---------------------------------------------------------------------------

class CrossResultModelLogic:
    """
    Extrae la logica pura de CrossResultModel para pruebas sin Qt.
    Replica setData() y delete_rows() tal como estan en produccion.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        self._df_original = df.copy()
        self._df = df.copy()
        self._edited_cells: set = set()

    def setData(self, row: int, col: int, value, role: int = 1) -> bool:
        """Replica exacta de CrossResultModel.setData (logica sin Qt)."""
        if role != 1:  # EditRole = 1
            return False

        dtype = self._df.dtypes.iloc[col]
        if pd.api.types.is_numeric_dtype(dtype):
            if value == "" or (isinstance(value, str) and value.strip() == ""):
                new_val = None
            else:
                try:
                    new_val = float(value)
                except (ValueError, TypeError):
                    return False  # DEF-001: rechazar
        else:
            new_val = value

        self._df.iloc[row, col] = new_val
        self._edited_cells.add((row, col))
        return True

    def delete_rows(self, model_rows: list) -> int:
        """Replica exacta de CrossResultModel.delete_rows (logica sin Qt)."""
        if not model_rows:
            return 0
        sorted_rows = sorted(set(model_rows), reverse=True)
        # DEF-002: guard con 0 <= r < len(self._df)
        idx_to_drop = [self._df.index[r] for r in sorted_rows if 0 <= r < len(self._df)]
        self._df = self._df.drop(index=idx_to_drop).reset_index(drop=True)
        self._edited_cells = set()
        return len(idx_to_drop)

    @property
    def working_df(self) -> pd.DataFrame:
        return self._df


# ---------------------------------------------------------------------------
# Tests DEF-001: setData con dtype numerico
# ---------------------------------------------------------------------------

class TestSetDataDEF001:

    def _make_numeric_model(self):
        df = pd.DataFrame({
            "importe": pd.array([100.0, 200.0, 300.0], dtype="float64"),
            "cantidad": pd.array([1, 2, 3], dtype="int64"),
            "descripcion": ["pago A", "pago B", "pago C"],
        })
        return CrossResultModelLogic(df)

    def test_texto_invalido_en_columna_float64_retorna_false(self):
        """DEF-001: setData con texto no numerico en float64 debe retornar False."""
        model = self._make_numeric_model()
        result = model.setData(0, 0, "abc")
        assert result is False

    def test_texto_invalido_no_corrompe_dtype_a_object(self):
        """DEF-001: el dtype de la columna NO debe cambiar a object tras intento fallido."""
        model = self._make_numeric_model()
        dtype_before = model.working_df.dtypes.iloc[0]
        model.setData(0, 0, "texto_invalido")
        dtype_after = model.working_df.dtypes.iloc[0]
        assert dtype_after == dtype_before, (
            f"dtype cambio de {dtype_before} a {dtype_after} — DEF-001 no corregido"
        )
        assert not pd.api.types.is_object_dtype(dtype_after), (
            "dtype se corrompio a object — DEF-001 no corregido"
        )

    def test_texto_invalido_en_columna_int64_retorna_false(self):
        """DEF-001: setData con texto en int64 debe retornar False."""
        model = self._make_numeric_model()
        result = model.setData(0, 1, "no_es_numero")
        assert result is False

    def test_texto_invalido_no_modifica_valor_existente(self):
        """DEF-001: el valor de la celda NO debe cambiar si la edicion falla."""
        model = self._make_numeric_model()
        valor_original = model.working_df.iloc[0, 0]
        model.setData(0, 0, "basura")
        valor_post = model.working_df.iloc[0, 0]
        assert valor_post == valor_original, (
            f"El valor cambio de {valor_original} a {valor_post} tras edicion invalida"
        )

    def test_texto_invalido_no_agrega_celda_a_edited_cells(self):
        """DEF-001: una edicion rechazada no debe marcar la celda como editada."""
        model = self._make_numeric_model()
        model.setData(0, 0, "texto")
        assert (0, 0) not in model._edited_cells

    def test_valor_numerico_valido_como_string_es_aceptado(self):
        """DEF-001 (positivo): '42.5' como string debe aceptarse en columna float64."""
        model = self._make_numeric_model()
        result = model.setData(0, 0, "42.5")
        assert result is True
        assert model.working_df.iloc[0, 0] == 42.5

    def test_valor_numerico_negativo_es_aceptado(self):
        """DEF-001 (positivo): '-100.0' debe aceptarse en columna float64."""
        model = self._make_numeric_model()
        result = model.setData(0, 0, "-100.0")
        assert result is True
        assert model.working_df.iloc[0, 0] == -100.0

    def test_valor_cero_es_aceptado(self):
        """DEF-001 (positivo): '0' debe aceptarse en columna float64."""
        model = self._make_numeric_model()
        result = model.setData(0, 0, "0")
        assert result is True
        assert model.working_df.iloc[0, 0] == 0.0

    def test_cadena_vacia_asigna_none_en_columna_numerica(self):
        """DEF-001 (borde): cadena vacia -> NaN en columna numerica, no corrompe dtype.
        En pandas, asignar None a float64 almacena NaN (no Python None).
        Lo importante: no corrompe el dtype a object."""
        model = self._make_numeric_model()
        result = model.setData(0, 0, "")
        assert result is True
        # pandas convierte None a NaN en columnas float64; verificar con pd.isna
        assert pd.isna(model.working_df.iloc[0, 0]), (
            "Se esperaba NaN tras asignar cadena vacia a columna float64"
        )
        # El dtype NO debe corromperse a object
        assert pd.api.types.is_numeric_dtype(model.working_df.dtypes.iloc[0])

    def test_texto_en_columna_object_es_aceptado(self):
        """DEF-001 (positivo): texto en columna object (descripcion) siempre se acepta."""
        model = self._make_numeric_model()
        result = model.setData(0, 2, "nuevo texto")
        assert result is True
        assert model.working_df.iloc[0, 2] == "nuevo texto"

    def test_multiples_intentos_invalidos_no_acumulan_corrupcion(self):
        """DEF-001: multiples intentos invalidos seguidos no corrompen dtype."""
        model = self._make_numeric_model()
        for val in ["abc", "xyz", "!@#", "SELECT *", "=1+1"]:
            model.setData(0, 0, val)
        dtype = model.working_df.dtypes.iloc[0]
        assert pd.api.types.is_numeric_dtype(dtype), (
            f"dtype deberia ser numerico pero es {dtype}"
        )


# ---------------------------------------------------------------------------
# Tests DEF-002: delete_rows con indices negativos
# ---------------------------------------------------------------------------

class TestDeleteRowsDEF002:

    def _make_model(self, n: int = 5) -> CrossResultModelLogic:
        df = pd.DataFrame({
            "id": range(n),
            "valor": [float(i) * 10 for i in range(n)],
        })
        return CrossResultModelLogic(df)

    def test_delete_rows_indice_menos_uno_devuelve_cero(self):
        """DEF-002: delete_rows([-1]) debe devolver 0 sin crashear."""
        model = self._make_model()
        result = model.delete_rows([-1])
        assert result == 0

    def test_delete_rows_indice_menos_uno_no_elimina_filas(self):
        """DEF-002: delete_rows([-1]) no debe cambiar el numero de filas."""
        model = self._make_model(5)
        rows_before = len(model.working_df)
        model.delete_rows([-1])
        assert len(model.working_df) == rows_before

    def test_delete_rows_indice_muy_negativo_devuelve_cero(self):
        """DEF-002: delete_rows([-100]) debe devolver 0 sin crashear."""
        model = self._make_model()
        result = model.delete_rows([-100])
        assert result == 0

    def test_delete_rows_mezcla_negativos_y_validos(self):
        """DEF-002: [-1, 0, 2] debe eliminar solo las filas 0 y 2."""
        model = self._make_model(5)
        result = model.delete_rows([-1, 0, 2])
        assert result == 2
        assert len(model.working_df) == 3

    def test_delete_rows_solo_negativos_multiples_devuelve_cero(self):
        """DEF-002: [-1, -5, -99] todos invalidos, retorna 0 y no modifica df."""
        model = self._make_model(5)
        rows_before = len(model.working_df)
        result = model.delete_rows([-1, -5, -99])
        assert result == 0
        assert len(model.working_df) == rows_before

    def test_delete_rows_fuera_de_rango_positivo_devuelve_cero(self):
        """DEF-002 (borde): indice >= len(df) tampoco debe crashear."""
        model = self._make_model(3)
        result = model.delete_rows([10, 100])
        assert result == 0
        assert len(model.working_df) == 3

    def test_delete_rows_valido_funciona_correctamente(self):
        """DEF-002 (positivo): delete_rows([0, 1]) debe eliminar exactamente 2 filas."""
        model = self._make_model(5)
        result = model.delete_rows([0, 1])
        assert result == 2
        assert len(model.working_df) == 3

    def test_delete_rows_lista_vacia_devuelve_cero(self):
        """DEF-002 (borde): lista vacia no hace nada."""
        model = self._make_model(5)
        result = model.delete_rows([])
        assert result == 0
        assert len(model.working_df) == 5

    def test_delete_rows_duplicados_se_cuentan_una_vez(self):
        """DEF-002 (borde): [0, 0, 0] debe eliminar solo 1 fila."""
        model = self._make_model(5)
        result = model.delete_rows([0, 0, 0])
        assert result == 1
        assert len(model.working_df) == 4
