"""
ui/result_screen.py — Pantalla de resultado con scroll virtual.

HU-05: visualizacion, filtrado, edicion, borrado y exportacion del resultado.
Usa QAbstractTableModel + QSortFilterProxyModel para scroll virtual (D-02).
Muestra dialogo explicito cuando el resultado tiene 0 filas.

Funcionalidades nuevas (extension):
  - Busqueda rapida en tiempo real (delay 300 ms).
  - Filtros por columna apilables con chips/badges.
  - Borrado de filas seleccionadas (copia de trabajo; restaurable).
  - Edicion inline de celdas con highlight amarillo.
  - Contador de filas N visibles / M total cuando hay filtros activos.
  - "Restaurar original" revierte ediciones y borrados.

RN-019: el log de auditoria NO contiene valores de celdas, CUILs, nombres
ni importes. Tampoco los valores ingresados en los filtros.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QDate,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

import pandas as pd

from audit.logger import AuditLogger, make_timestamp
from data.models import AuditEntry, CrossResult
from engine.exporter import XlsxExporter
from engine.filter_ops import FilterCondition, apply_filters
from ui.stats_panel import StatsPanel
from ui.login_screen import (
    COLOR_ERROR,
    COLOR_PRIMARY,
    COLOR_PRIMARY_LIGHT,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MID,
    COLOR_WARNING,
    STYLE_BTN_PRIMARY,
    STYLE_SCREEN_TITLE,
)

# Color de celda editada (highlight amarillo claro, RN-019).
COLOR_EDITED_CELL = "#fffde7"

# Etiquetas para el combo de operadores.
OPERATOR_LABELS: list[tuple[str, str]] = [
    ("contiene",        "contiene"),
    ("igual_a",         "igual a"),
    ("empieza_con",     "empieza con"),
    ("mayor_que",       "mayor que"),
    ("menor_que",       "menor que"),
    ("es_vacio",        "es vacío"),
    ("no_es_vacio",     "no es vacío"),
    ("fecha_antes_de",  "fecha ≤"),
    ("fecha_despues_de","fecha ≥"),
    ("fecha_entre",     "fecha entre"),
]

# Operadores que no requieren campo de valor.
_OPS_SIN_VALOR: frozenset[str] = frozenset({"es_vacio", "no_es_vacio"})

# Operadores de fecha que usan dos campos de valor.
_OPS_DOS_VALORES: frozenset[str] = frozenset({"fecha_entre"})

# Todos los operadores de fecha (usan QDateEdit en lugar de QLineEdit).
_OPS_FECHA: frozenset[str] = frozenset({"fecha_antes_de", "fecha_despues_de", "fecha_entre"})


# ---------------------------------------------------------------------------
# Modelo de tabla editable
# ---------------------------------------------------------------------------

class CrossResultModel(QAbstractTableModel):
    """
    QAbstractTableModel que envuelve un DataFrame de pandas.
    Solo materializa las celdas visibles (scroll virtual).

    Trabaja sobre self._df (copia de trabajo).
    self._df_original guarda el DataFrame intacto para "Restaurar original".
    Las celdas editadas se trackean en self._edited_cells (set de (row, col)).
    """

    def __init__(self, df: pd.DataFrame, parent=None) -> None:
        super().__init__(parent)
        self._df_original: pd.DataFrame = df.copy()
        self._df: pd.DataFrame = df.copy()
        self._edited_cells: set[tuple[int, int]] = set()

    # ------------------------------------------------------------------
    # QAbstractTableModel interface
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._df)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None

        row, col = index.row(), index.column()

        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            value = self._df.iloc[row, col]
            if pd.isna(value) if not isinstance(value, str) else False:
                return ""
            return str(value) if value is not None else ""

        if role == Qt.ItemDataRole.BackgroundRole:
            if (row, col) in self._edited_cells:
                return QColor(COLOR_EDITED_CELL)
            if row % 2 == 1:
                return QColor("#f3f7fb")

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return str(self._df.columns[section])
            else:
                return str(section + 1)
        if role == Qt.ItemDataRole.ForegroundRole:
            if orientation == Qt.Orientation.Horizontal:
                return QColor("white")
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        if role != Qt.ItemDataRole.EditRole:
            return False

        row, col = index.row(), index.column()
        current = self._df.iloc[row, col]

        # Convertir al tipo de la columna si es posible.
        # DEF-001: si el valor es incompatible con el dtype numerico, rechazar
        # la edicion (retornar False) en lugar de corromper el dtype de la columna.
        dtype = self._df.dtypes.iloc[col]
        if pd.api.types.is_numeric_dtype(dtype):
            if value == "" or (isinstance(value, str) and value.strip() == ""):
                new_val: Any = None
            else:
                try:
                    new_val = float(value)
                except (ValueError, TypeError):
                    return False  # Rechazar: no corromper dtype numerico
        else:
            new_val = value

        self._df.iloc[row, col] = new_val
        self._edited_cells.add((row, col))
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole])
        return True

    # ------------------------------------------------------------------
    # Operaciones de copia de trabajo
    # ------------------------------------------------------------------

    def delete_rows(self, model_rows: list[int]) -> int:
        """
        Elimina filas de la copia de trabajo por indice de fila del modelo.
        Devuelve la cantidad de filas eliminadas.
        """
        if not model_rows:
            return 0

        sorted_rows = sorted(set(model_rows), reverse=True)
        self.beginResetModel()
        # DEF-002: excluir indices fuera de rango, incluyendo negativos.
        idx_to_drop = [self._df.index[r] for r in sorted_rows if 0 <= r < len(self._df)]
        self._df = self._df.drop(index=idx_to_drop).reset_index(drop=True)
        # Limpiar edited_cells ya que los indices cambian.
        self._edited_cells = set()
        self.endResetModel()
        return len(idx_to_drop)

    def delete_columns(self, col_indices: list[int]) -> int:
        """
        Elimina columnas por indice de columna del modelo (copia de trabajo).
        Devuelve la cantidad de columnas eliminadas.

        DEF-002 aplicado: solo procesa indices 0 <= i < columnCount().
        """
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
        self.beginResetModel()
        self._df = self._df.drop(columns=cols_to_drop, errors="ignore")
        # Los indices de celdas editadas son invalidos tras cambio de columnas.
        self._edited_cells = set()
        self.endResetModel()
        return len(cols_to_drop)

    def restore_original(self) -> None:
        """Revierte la copia de trabajo al DataFrame original."""
        self.beginResetModel()
        self._df = self._df_original.copy()
        self._edited_cells = set()
        self.endResetModel()

    @property
    def edited_cells(self) -> set[tuple[int, int]]:
        return self._edited_cells

    @property
    def working_df(self) -> pd.DataFrame:
        """DataFrame de trabajo (con ediciones y borrados aplicados)."""
        return self._df

    @property
    def original_row_count(self) -> int:
        return len(self._df_original)


# ---------------------------------------------------------------------------
# Proxy model con filtros multiples
# ---------------------------------------------------------------------------

class MultiFilterProxyModel(QSortFilterProxyModel):
    """
    Proxy que filtra filas segun una lista de FilterCondition (AND)
    y una cadena de busqueda rapida.

    Llama a apply_filters() de engine/filter_ops.py para calcular
    el conjunto de indices de fila visibles.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._conditions: list[FilterCondition] = []
        self._quick_search: str = ""
        self._visible_source_rows: set[int] = set()  # indices en el modelo fuente

    def set_filters(self, conditions: list[FilterCondition], quick_search: str) -> None:
        self._conditions = conditions
        self._quick_search = quick_search
        self._recompute_visible_rows()
        self.invalidateFilter()

    def _recompute_visible_rows(self) -> None:
        source: CrossResultModel | None = self.sourceModel()  # type: ignore[assignment]
        if source is None:
            self._visible_source_rows = set()
            return

        df = source.working_df
        if df.empty or (not self._conditions and not self._quick_search.strip()):
            # Sin filtros: todas las filas son visibles.
            self._visible_source_rows = set(range(len(df)))
            return

        filtered = apply_filters(df, self._conditions, self._quick_search)
        # apply_filters devuelve una copia con los indices originales preservados.
        # Necesitamos posiciones (0-based) en el DataFrame de trabajo actual.
        pos_map = {idx: pos for pos, idx in enumerate(df.index)}
        self._visible_source_rows = {pos_map[i] for i in filtered.index if i in pos_map}

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._conditions and not self._quick_search.strip():
            return True
        return source_row in self._visible_source_rows

    def visible_row_count(self) -> int:
        return self.rowCount()

    def map_proxy_rows_to_source(self, proxy_rows: list[int]) -> list[int]:
        """Convierte indices de fila del proxy a indices de fila del modelo fuente."""
        result = []
        for pr in proxy_rows:
            src_idx = self.mapToSource(self.index(pr, 0))
            result.append(src_idx.row())
        return result


# ---------------------------------------------------------------------------
# Widget chip de filtro activo
# ---------------------------------------------------------------------------

class FilterChip(QFrame):
    """Chip visual para un filtro activo. Emite remove_requested() al clickar X."""

    remove_requested = Signal(object)  # emite self

    def __init__(self, condition: FilterCondition, parent=None) -> None:
        super().__init__(parent)
        self.condition = condition
        self.setStyleSheet(
            f"background-color: {COLOR_PRIMARY_LIGHT}; "
            f"border: 1px solid #a8c4e0; border-radius: 10px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 4, 3)
        layout.setSpacing(4)

        op_label = dict(OPERATOR_LABELS).get(condition.operator, condition.operator)
        if condition.operator in _OPS_SIN_VALOR:
            text = f"{condition.column} {op_label}"
        elif condition.operator in _OPS_DOS_VALORES:
            # Para fecha_entre no mostrar las fechas concretas (consistencia con RN-019).
            text = f"{condition.column} {op_label}"
        else:
            text = f"{condition.column} {op_label} ..."

        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size: 11px; color: {COLOR_TEXT_DARK}; background: transparent; border: none;"
        )
        layout.addWidget(lbl)

        btn_x = QPushButton("x")
        btn_x.setFixedSize(16, 16)
        btn_x.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; background: transparent; border: none; "
            f"font-size: 10px; font-weight: bold; padding: 0;"
        )
        btn_x.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(btn_x)


# ---------------------------------------------------------------------------
# Pantalla de resultado
# ---------------------------------------------------------------------------

class ResultScreen(QWidget):
    """
    Pantalla de resultado con tabla virtual, filtros, edicion, borrado y exportacion.

    Emite new_cross_requested() para volver al inicio con estado limpio.
    Emite back_to_config_requested() para ajustar el cruce.
    Emite use_as_base_requested(CrossResult) para cruce secuencial.
    """

    new_cross_requested = Signal()
    back_to_config_requested = Signal()
    use_as_base_requested = Signal(object)  # emite CrossResult

    def __init__(self, audit_logger: AuditLogger, parent=None) -> None:
        super().__init__(parent)
        self._logger = audit_logger
        self._result: CrossResult | None = None
        self._current_user: str = ""
        self._exporter = XlsxExporter()

        self._source_model: CrossResultModel | None = None
        self._proxy_model: MultiFilterProxyModel | None = None
        self._active_conditions: list[FilterCondition] = []
        self._active_chips: list[FilterChip] = []

        # Timer para el delay de busqueda rapida.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filters_now)

        self._build_ui()

    # ------------------------------------------------------------------
    # Construccion de la UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 16, 24, 16)
        main_layout.setSpacing(8)

        # --- Titulo ---
        self._header = QLabel("Resultado del cruce")
        self._header.setStyleSheet(STYLE_SCREEN_TITLE)
        main_layout.addWidget(self._header)

        # --- Panel de estadisticas ---
        stats_frame = QFrame()
        stats_frame.setStyleSheet(
            f"background-color: {COLOR_PRIMARY_LIGHT}; "
            f"border: 1px solid #c8d8ea; border-radius: 6px;"
        )
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(14, 10, 14, 10)
        stats_layout.setSpacing(24)

        self._lbl_rows = self._make_stat_label("Filas", "—")
        self._lbl_cols = self._make_stat_label("Columnas", "—")
        self._lbl_join = self._make_stat_label("Tipo de cruce", "—")
        self._lbl_duration = self._make_stat_label("Tiempo", "—")

        for widget in [self._lbl_rows, self._lbl_cols, self._lbl_join, self._lbl_duration]:
            stats_layout.addWidget(widget)
        stats_layout.addStretch()

        # Boton toggle para el panel de estadisticas descriptivas.
        self._btn_toggle_stats = QPushButton("Ver estadisticas")
        self._btn_toggle_stats.setFixedHeight(28)
        self._btn_toggle_stats.setStyleSheet(
            f"color: {COLOR_PRIMARY}; border: 1.5px solid {COLOR_PRIMARY}; "
            f"border-radius: 4px; font-size: 11px; font-weight: bold; "
            f"padding: 2px 10px; background: white;"
        )
        self._btn_toggle_stats.setToolTip("Ejecuta un cruce primero")
        self._btn_toggle_stats.setEnabled(False)
        self._btn_toggle_stats.clicked.connect(self._on_toggle_stats)
        stats_layout.addWidget(self._btn_toggle_stats)

        main_layout.addWidget(stats_frame)

        # Panel colapsable de estadisticas descriptivas.
        self._stats_panel = StatsPanel()
        self._stats_panel.stats_computed.connect(self._on_stats_computed)
        main_layout.addWidget(self._stats_panel)

        # --- Advertencias ---
        self._warnings_label = QLabel("")
        self._warnings_label.setWordWrap(True)
        self._warnings_label.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 11px; "
            f"background-color: #fff7ee; border-radius: 4px; padding: 6px 10px;"
        )
        self._warnings_label.hide()
        main_layout.addWidget(self._warnings_label)

        # --- Barra de filtros ---
        self._filter_frame = QFrame()
        self._filter_frame.setStyleSheet(
            "background-color: #f8fafc; border: 1px solid #dce6f0; border-radius: 6px;"
        )
        filter_outer = QVBoxLayout(self._filter_frame)
        filter_outer.setContentsMargins(10, 8, 10, 8)
        filter_outer.setSpacing(6)

        # Fila 1: busqueda rapida
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        lbl_search = QLabel("Buscar:")
        lbl_search.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MID}; font-weight: bold;")
        search_row.addWidget(lbl_search)

        self._input_quick_search = QLineEdit()
        self._input_quick_search.setPlaceholderText("Buscar en todas las columnas...")
        self._input_quick_search.setMinimumHeight(28)
        self._input_quick_search.setStyleSheet(
            f"border: 1px solid #ccd6e0; border-radius: 4px; "
            f"padding: 2px 8px; font-size: 12px; color: {COLOR_TEXT_DARK}; "
            f"background-color: white;"
        )
        self._input_quick_search.textChanged.connect(self._on_quick_search_changed)
        search_row.addWidget(self._input_quick_search, 1)

        filter_outer.addLayout(search_row)

        # Fila 2: filtro por columna
        col_filter_row = QHBoxLayout()
        col_filter_row.setSpacing(6)

        lbl_col = QLabel("Columna:")
        lbl_col.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_MID};")
        col_filter_row.addWidget(lbl_col)

        self._combo_column = QComboBox()
        self._combo_column.setMinimumHeight(28)
        self._combo_column.setMinimumWidth(150)
        self._combo_column.setStyleSheet(
            f"border: 1px solid #ccd6e0; border-radius: 4px; "
            f"padding: 2px 6px; font-size: 12px; background-color: white;"
        )
        col_filter_row.addWidget(self._combo_column)

        self._combo_operator = QComboBox()
        self._combo_operator.setMinimumHeight(28)
        self._combo_operator.setMinimumWidth(110)
        self._combo_operator.setStyleSheet(
            f"border: 1px solid #ccd6e0; border-radius: 4px; "
            f"padding: 2px 6px; font-size: 12px; background-color: white;"
        )
        for key, label in OPERATOR_LABELS:
            self._combo_operator.addItem(label, key)
        self._combo_operator.currentIndexChanged.connect(self._on_operator_changed)
        col_filter_row.addWidget(self._combo_operator)

        self._input_filter_value = QLineEdit()
        self._input_filter_value.setPlaceholderText("Valor...")
        self._input_filter_value.setMinimumHeight(28)
        self._input_filter_value.setMinimumWidth(120)
        self._input_filter_value.setStyleSheet(
            f"border: 1px solid #ccd6e0; border-radius: 4px; "
            f"padding: 2px 8px; font-size: 12px; color: {COLOR_TEXT_DARK}; "
            f"background-color: white;"
        )
        col_filter_row.addWidget(self._input_filter_value)

        # Campo "Hasta" para operador fecha_entre (oculto por defecto).
        self._input_filter_value2 = QLineEdit()
        self._input_filter_value2.setPlaceholderText("Hasta (dd/mm/aaaa)")
        self._input_filter_value2.setMinimumHeight(28)
        self._input_filter_value2.setMinimumWidth(130)
        self._input_filter_value2.setStyleSheet(
            f"border: 1px solid #ccd6e0; border-radius: 4px; "
            f"padding: 2px 8px; font-size: 12px; color: {COLOR_TEXT_DARK}; "
            f"background-color: white;"
        )
        self._input_filter_value2.hide()
        col_filter_row.addWidget(self._input_filter_value2)

        # QDateEdit principal para operadores de fecha (oculto por defecto).
        self._date_edit_value = QDateEdit()
        self._date_edit_value.setCalendarPopup(True)
        self._date_edit_value.setDisplayFormat("dd/MM/yyyy")
        self._date_edit_value.setDate(QDate.currentDate())
        self._date_edit_value.setMinimumHeight(28)
        self._date_edit_value.setMinimumWidth(120)
        self._date_edit_value.hide()
        col_filter_row.addWidget(self._date_edit_value)

        # QDateEdit secundario para fecha_entre — campo "Hasta" (oculto por defecto).
        self._date_edit_value2 = QDateEdit()
        self._date_edit_value2.setCalendarPopup(True)
        self._date_edit_value2.setDisplayFormat("dd/MM/yyyy")
        self._date_edit_value2.setDate(QDate.currentDate())
        self._date_edit_value2.setMinimumHeight(28)
        self._date_edit_value2.setMinimumWidth(120)
        self._date_edit_value2.hide()
        col_filter_row.addWidget(self._date_edit_value2)

        self._btn_apply_filter = QPushButton("Aplicar filtro")
        self._btn_apply_filter.setMinimumHeight(28)
        self._btn_apply_filter.setStyleSheet(
            f"background-color: {COLOR_PRIMARY}; color: white; font-size: 11px; "
            f"font-weight: bold; border-radius: 4px; border: none; padding: 2px 10px;"
        )
        self._btn_apply_filter.clicked.connect(self._on_add_filter)
        col_filter_row.addWidget(self._btn_apply_filter)

        self._btn_clear_filters = QPushButton("Limpiar filtros")
        self._btn_clear_filters.setMinimumHeight(28)
        self._btn_clear_filters.setStyleSheet(
            f"color: {COLOR_ERROR}; border: 1px solid {COLOR_ERROR}; "
            f"border-radius: 4px; font-size: 11px; padding: 2px 10px; background: white;"
        )
        self._btn_clear_filters.clicked.connect(self._on_clear_all_filters)
        col_filter_row.addWidget(self._btn_clear_filters)

        col_filter_row.addStretch()

        self._btn_restore = QPushButton("Restaurar original")
        self._btn_restore.setMinimumHeight(28)
        self._btn_restore.setStyleSheet(
            f"color: #7b3f00; border: 1px solid #e67e22; "
            f"border-radius: 4px; font-size: 11px; padding: 2px 10px; background: #fff3e0;"
        )
        self._btn_restore.clicked.connect(self._on_restore_original)
        col_filter_row.addWidget(self._btn_restore)

        filter_outer.addLayout(col_filter_row)

        # Fila 3: chips de filtros activos
        self._chips_row = QHBoxLayout()
        self._chips_row.setSpacing(6)
        self._chips_row.addStretch()
        filter_outer.addLayout(self._chips_row)
        # La fila de chips solo es visible cuando hay chips.
        self._chips_container = QWidget()
        self._chips_container.setStyleSheet("background: transparent;")
        self._chips_layout = QHBoxLayout(self._chips_container)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(6)
        self._chips_layout.addStretch()
        filter_outer.addWidget(self._chips_container)
        self._chips_container.hide()

        self._filter_frame.hide()  # se muestra cuando hay datos
        main_layout.addWidget(self._filter_frame)

        # --- Tabla ---
        self._table = QTableView()
        self._table.setAlternatingRowColors(False)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {COLOR_PRIMARY}; color: white; "
            f"  font-weight: bold; font-size: 11px; "
            f"  border: 1px solid #1a5080; padding: 4px 6px;"
            f"}}"
        )
        self._table.verticalHeader().setDefaultSectionSize(24)
        # Habilitar seleccion de filas completas desde el header vertical.
        self._table.verticalHeader().setSectionsClickable(True)
        self._table.verticalHeader().setSelectionMode(
            QHeaderView.SelectionMode.ExtendedSelection  # type: ignore[attr-defined]
        )
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(False)
        self._table.setStyleSheet(
            f"QTableView {{ gridline-color: #d8e4f0; font-size: 12px; color: {COLOR_TEXT_DARK}; }}"
        )
        # Menu contextual de filas (clic derecho sobre celdas).
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        # Menu contextual de columnas (clic derecho sobre header horizontal).
        self._table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.horizontalHeader().customContextMenuRequested.connect(
            self._on_header_context_menu
        )
        # Activar edicion con doble click (comportamiento default de QTableView cuando el modelo es editable).
        self._table.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked | QTableView.EditTrigger.SelectedClicked
        )
        self._table.selectionModel()  # se asigna al cargar el modelo
        main_layout.addWidget(self._table, 1)

        # --- Fila de botones de accion sobre filas ---
        self._action_row_widget = QWidget()
        action_row = QHBoxLayout(self._action_row_widget)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)

        self._btn_delete_rows = QPushButton("Eliminar filas seleccionadas")
        self._btn_delete_rows.setMinimumHeight(30)
        self._btn_delete_rows.setStyleSheet(
            f"color: {COLOR_ERROR}; border: 1.5px solid {COLOR_ERROR}; "
            f"border-radius: 4px; font-size: 12px; font-weight: bold; "
            f"padding: 2px 12px; background: white;"
        )
        self._btn_delete_rows.setEnabled(False)
        self._btn_delete_rows.clicked.connect(self._on_delete_selected_rows)
        action_row.addWidget(self._btn_delete_rows)

        action_row.addStretch()
        self._action_row_widget.hide()
        main_layout.addWidget(self._action_row_widget)

        # --- Botones principales ---
        btn_row = QHBoxLayout()

        self._btn_back_config = QPushButton("← Ajustar configuración")
        self._btn_back_config.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #ccd6e0; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        self._btn_back_config.clicked.connect(self.back_to_config_requested)
        btn_row.addWidget(self._btn_back_config)

        self._btn_new = QPushButton("Nuevo cruce")
        self._btn_new.setStyleSheet(
            f"color: {COLOR_PRIMARY}; border: 1.5px solid {COLOR_PRIMARY}; "
            f"border-radius: 4px; padding: 4px 14px; font-weight: bold;"
        )
        self._btn_new.clicked.connect(self.new_cross_requested)
        btn_row.addWidget(self._btn_new)

        self._btn_use_as_base = QPushButton("↩ Usar como base para nuevo cruce")
        self._btn_use_as_base.setToolTip(
            "Usá este resultado como archivo de entrada para cruzarlo con otro Excel"
        )
        self._btn_use_as_base.setStyleSheet(
            f"color: #7b3f00; background-color: #fff3e0; "
            f"border: 1.5px solid #e67e22; border-radius: 4px; "
            f"padding: 4px 14px; font-weight: bold;"
        )
        self._btn_use_as_base.clicked.connect(self._on_use_as_base)
        btn_row.addWidget(self._btn_use_as_base)

        btn_row.addStretch()

        self._btn_export = QPushButton("Exportar a Excel (.xlsx)  ↓")
        self._btn_export.setMinimumHeight(42)
        self._btn_export.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; "
            "font-size: 13px; border-radius: 5px; border: none; padding: 4px 18px;"
        )
        self._btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(self._btn_export)

        main_layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Helpers de UI
    # ------------------------------------------------------------------

    def _make_stat_label(self, title: str, value: str) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(
            f"font-size: 10px; color: {COLOR_TEXT_MID}; font-weight: bold; "
            f"text-transform: uppercase; background: transparent;"
        )
        layout.addWidget(lbl_title)

        lbl_value = QLabel(value)
        lbl_value.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {COLOR_PRIMARY}; "
            f"background: transparent;"
        )
        lbl_value.setObjectName(f"stat_value_{title}")
        layout.addWidget(lbl_value)

        container._value_label = lbl_value  # type: ignore[attr-defined]
        return container

    def _set_stat(self, container: QWidget, value: str) -> None:
        container._value_label.setText(value)  # type: ignore[attr-defined]

    def _update_rows_stat(self) -> None:
        """Actualiza el chip de Filas con N visibles / M total si hay filtros."""
        if self._source_model is None:
            self._set_stat(self._lbl_rows, "—")
            return

        total = self._source_model.original_row_count
        has_filters = bool(self._active_conditions) or bool(
            self._input_quick_search.text().strip()
        )
        if has_filters and self._proxy_model is not None:
            visible = self._proxy_model.visible_row_count()
            self._set_stat(self._lbl_rows, f"{visible:,} / {total:,}")
        else:
            # Mostrar filas actuales en la copia de trabajo
            current = len(self._source_model.working_df)
            if current != total:
                self._set_stat(self._lbl_rows, f"{current:,} / {total:,} orig.")
            else:
                self._set_stat(self._lbl_rows, f"{total:,}")

    # ------------------------------------------------------------------
    # Carga de resultado
    # ------------------------------------------------------------------

    def show_result(self, result: CrossResult, current_user: str = "") -> None:
        """Carga el resultado en la tabla."""
        self._result = result
        self._current_user = current_user

        # Limpiar estado de filtros previos.
        self._active_conditions = []
        self._input_quick_search.blockSignals(True)
        self._input_quick_search.clear()
        self._input_quick_search.blockSignals(False)
        self._clear_chips_ui()

        title = f"Resultado: {result.name}" if result.name else "Resultado del cruce"
        self._header.setText(title)

        if result.df is not None and not result.df.empty:
            self._source_model = CrossResultModel(result.df)
            self._proxy_model = MultiFilterProxyModel(self)
            self._proxy_model.setSourceModel(self._source_model)
            self._table.setModel(self._proxy_model)
            # Reconectar selectionChanged despues de asignar el modelo.
            self._table.selectionModel().selectionChanged.connect(
                self._on_selection_changed
            )
            # Poblar combo de columnas.
            self._combo_column.clear()
            for col_name in result.df.columns:
                self._combo_column.addItem(str(col_name))
            self._filter_frame.show()
            self._action_row_widget.show()
        else:
            self._source_model = None
            self._proxy_model = None
            self._table.setModel(None)
            self._filter_frame.hide()
            self._action_row_widget.hide()

        cols = len(result.df.columns) if result.df is not None else 0
        self._set_stat(self._lbl_cols, str(cols))
        self._set_stat(self._lbl_join, result.join_type)
        self._set_stat(self._lbl_duration, f"{result.duration_ms:.0f} ms")
        self._update_rows_stat()

        if result.warnings:
            self._warnings_label.setText(
                "Advertencias:\n" + "\n".join(f"• {w}" for w in result.warnings)
            )
            self._warnings_label.show()
        else:
            self._warnings_label.hide()

        if result.row_count == 0:
            self._table.setModel(None)
            QMessageBox.warning(
                self,
                "El cruce no tiene resultados",
                "No se encontraron filas coincidentes.\n\n"
                "El archivo exportado tendrá solo los encabezados de columna, "
                "sin datos.\n\n"
                "Podés volver a la configuración y probar con otro tipo de cruce "
                "o activar la normalización de claves.",
            )

        # Actualizar datos del panel de estadisticas (no calcula aun, solo prepara).
        if result.df is not None and self._source_model is not None:
            self._stats_panel.set_data(
                df=self._source_model.working_df,
                matched_rows=result.matched_rows,
                left_only_rows=result.left_only_rows,
                right_only_rows=result.right_only_rows,
            )
            self._btn_toggle_stats.setEnabled(True)
            self._btn_toggle_stats.setToolTip("")
        else:
            self._btn_toggle_stats.setEnabled(False)
            self._btn_toggle_stats.setToolTip("Ejecuta un cruce primero")
            self._stats_panel.hide()
            self._btn_toggle_stats.setText("Ver estadisticas")

    # ------------------------------------------------------------------
    # Filtros
    # ------------------------------------------------------------------

    def _on_quick_search_changed(self) -> None:
        self._search_timer.start()  # reinicia el timer en cada tecla

    def _on_operator_changed(self) -> None:
        op = self._combo_operator.currentData()

        if op in _OPS_FECHA:
            # Operador de fecha: ocultar QLineEdit, mostrar QDateEdit.
            self._input_filter_value.hide()
            self._input_filter_value2.hide()
            self._input_filter_value2.clear()
            self._date_edit_value.show()
            if op in _OPS_DOS_VALORES:
                # fecha_entre: mostrar ambos QDateEdit.
                self._date_edit_value2.show()
            else:
                self._date_edit_value2.hide()
        else:
            # Operador no-fecha: mostrar QLineEdit, ocultar QDateEdit.
            self._date_edit_value.hide()
            self._date_edit_value2.hide()
            self._input_filter_value.show()
            self._input_filter_value2.hide()
            self._input_filter_value2.clear()

            # Habilitar/deshabilitar campo de valor.
            needs_value = op not in _OPS_SIN_VALOR
            self._input_filter_value.setEnabled(needs_value)
            if not needs_value:
                self._input_filter_value.clear()
            self._input_filter_value.setPlaceholderText("Valor...")

    def _on_add_filter(self) -> None:
        if self._source_model is None:
            return

        col = self._combo_column.currentText()
        op = self._combo_operator.currentData()

        if op in _OPS_FECHA:
            # Leer valor desde QDateEdit en formato dd/MM/yyyy.
            val = self._date_edit_value.date().toString("dd/MM/yyyy")
            val2 = (
                self._date_edit_value2.date().toString("dd/MM/yyyy")
                if op in _OPS_DOS_VALORES
                else ""
            )
        else:
            val = self._input_filter_value.text().strip()
            val2 = self._input_filter_value2.text().strip() if op in _OPS_DOS_VALORES else ""

        if not col:
            return

        # Para operadores sin valor, val puede estar vacio.
        cond = FilterCondition(column=col, operator=op, value=val, value2=val2)
        self._active_conditions.append(cond)
        self._add_chip(cond)
        self._input_filter_value.clear()
        self._input_filter_value2.clear()
        self._apply_filters_now()

    def _on_clear_all_filters(self) -> None:
        self._active_conditions = []
        self._input_quick_search.blockSignals(True)
        self._input_quick_search.clear()
        self._input_quick_search.blockSignals(False)
        self._clear_chips_ui()
        self._apply_filters_now()

    def _on_restore_original(self) -> None:
        if self._source_model is None:
            return
        reply = QMessageBox.question(
            self,
            "Restaurar original",
            "Se revertirán todos los filtros, ediciones y filas eliminadas. "
            "¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._active_conditions = []
        self._input_quick_search.blockSignals(True)
        self._input_quick_search.clear()
        self._input_quick_search.blockSignals(False)
        self._clear_chips_ui()
        self._source_model.restore_original()

        if self._proxy_model is not None:
            self._proxy_model.set_filters([], "")

        self._update_rows_stat()

        # Invalidar el panel de estadisticas: el working_df cambio (RT-STATS-07).
        self._stats_panel.invalidate()

    def _apply_filters_now(self) -> None:
        if self._proxy_model is None:
            return
        qs = self._input_quick_search.text()
        self._proxy_model.set_filters(self._active_conditions, qs)
        self._update_rows_stat()

    # ------------------------------------------------------------------
    # Chips
    # ------------------------------------------------------------------

    def _add_chip(self, cond: FilterCondition) -> None:
        chip = FilterChip(cond, self)
        chip.remove_requested.connect(self._on_remove_chip)
        # Insertar antes del stretch.
        count = self._chips_layout.count()
        self._chips_layout.insertWidget(count - 1, chip)
        self._active_chips.append(chip)
        self._chips_container.show()

    def _on_remove_chip(self, chip: FilterChip) -> None:
        if chip.condition in self._active_conditions:
            self._active_conditions.remove(chip.condition)
        self._chips_layout.removeWidget(chip)
        chip.deleteLater()
        self._active_chips = [c for c in self._active_chips if c is not chip]
        if not self._active_chips:
            self._chips_container.hide()
        self._apply_filters_now()

    def _clear_chips_ui(self) -> None:
        for chip in list(self._active_chips):
            self._chips_layout.removeWidget(chip)
            chip.deleteLater()
        self._active_chips = []
        self._chips_container.hide()

    # ------------------------------------------------------------------
    # Borrado de filas
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        has_selection = len(self._table.selectionModel().selectedRows()) > 0
        self._btn_delete_rows.setEnabled(has_selection)

    def _get_selected_proxy_rows(self) -> list[int]:
        """Devuelve lista de indices de fila unicos seleccionados en el proxy."""
        indexes = self._table.selectionModel().selectedRows()
        return sorted({idx.row() for idx in indexes})

    def _on_delete_selected_rows(self) -> None:
        if self._source_model is None or self._proxy_model is None:
            return

        proxy_rows = self._get_selected_proxy_rows()
        if not proxy_rows:
            return

        n = len(proxy_rows)
        reply = QMessageBox.question(
            self,
            "Eliminar filas",
            f"¿Eliminar {n} fila(s)?\n\n"
            "Esta acción se puede deshacer con 'Restaurar original'.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Mapear a indices del modelo fuente antes de eliminar.
        source_rows = self._proxy_model.map_proxy_rows_to_source(proxy_rows)
        deleted = self._source_model.delete_rows(source_rows)

        # Recalcular filtros (los indices cambiaron).
        self._proxy_model._recompute_visible_rows()
        self._proxy_model.invalidateFilter()

        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._current_user,
            accion="ROWS_DELETED",
            filas_procesadas=deleted,
        ))

        self._update_rows_stat()
        self._btn_delete_rows.setEnabled(False)

        # Invalidar el panel de estadisticas (RT-STATS-07).
        self._stats_panel.invalidate()

    def _on_context_menu(self, pos) -> None:
        proxy_rows = self._get_selected_proxy_rows()
        if not proxy_rows:
            return
        menu = QMenu(self)
        n = len(proxy_rows)
        action_delete = menu.addAction(f"Eliminar fila(s) seleccionadas ({n})")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == action_delete:
            self._on_delete_selected_rows()

    def _on_header_context_menu(self, pos) -> None:
        """
        Menu contextual sobre el header horizontal para eliminar columnas.
        Si hay columnas seleccionadas (Ctrl+click), ofrece eliminarlas todas.
        Si no hay seleccion, ofrece eliminar la columna bajo el cursor.
        """
        if self._source_model is None or self._proxy_model is None:
            return

        header = self._table.horizontalHeader()
        col_under_cursor = header.logicalIndexAt(pos)
        if col_under_cursor < 0:
            return

        # Obtener columnas seleccionadas en el header (via seleccion de columnas).
        selected_cols = sorted({
            self._proxy_model.mapToSource(
                self._proxy_model.index(0, idx.column())
            ).column()
            for idx in self._table.selectionModel().selectedColumns()
        })

        if selected_cols:
            n = len(selected_cols)
            col_names = [str(self._source_model._df.columns[i]) for i in selected_cols]
            label = f"Eliminar columna(s) seleccionadas ({n})"
        else:
            # Mapear indice de proxy a modelo fuente.
            src_col = self._proxy_model.mapToSource(
                self._proxy_model.index(0, col_under_cursor)
            ).column()
            selected_cols = [src_col]
            col_names = [str(self._source_model._df.columns[src_col])]
            n = 1
            label = "Eliminar esta columna"

        menu = QMenu(self)
        action_del = menu.addAction(label)
        action = menu.exec(header.mapToGlobal(pos))

        if action != action_del:
            return

        reply = QMessageBox.question(
            self,
            "Eliminar columna(s)",
            f"¿Eliminar {n} columna(s)?\n\n"
            "Esta accion se puede deshacer con 'Restaurar original'.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted = self._source_model.delete_columns(selected_cols)

        # Recalcular filtros (el modelo cambio).
        if self._proxy_model is not None:
            self._proxy_model._recompute_visible_rows()
            self._proxy_model.invalidateFilter()

        # Actualizar stat de columnas.
        cols_remaining = len(self._source_model.working_df.columns)
        self._set_stat(self._lbl_cols, str(cols_remaining))
        self._update_rows_stat()

        # Audit log (RN-019: nombres de campo son metadata, no valores de celdas).
        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._current_user,
            accion="COLUMNS_DELETED",
            columnas=col_names,
            filas_procesadas=0,
        ))

        # Invalidar el panel de estadisticas (RT-STATS-07).
        self._stats_panel.invalidate()

    # ------------------------------------------------------------------
    # Uso como base para nuevo cruce
    # ------------------------------------------------------------------

    def _on_use_as_base(self) -> None:
        if self._result is None or self._result.df is None or self._result.df.empty:
            QMessageBox.warning(
                self,
                "Sin resultado",
                "No hay datos en el resultado actual para usar como base.",
            )
            return
        self.use_as_base_requested.emit(self._result)

    # ------------------------------------------------------------------
    # Panel de estadisticas descriptivas
    # ------------------------------------------------------------------

    def _on_toggle_stats(self) -> None:
        """Muestra u oculta el panel de estadisticas."""
        if self._stats_panel.isVisible():
            self._stats_panel.hide()
            self._btn_toggle_stats.setText("Ver estadisticas")
        else:
            self._stats_panel.show()
            self._btn_toggle_stats.setText("Ocultar estadisticas")

    def _on_stats_computed(self, result) -> None:
        """
        Log de auditoria al terminar el calculo de estadisticas (RN-019).
        RN-STATS-003: solo se loggean conteos y nombres de columnas.
        NO se loggean sumas, promedios, min/max, fechas extremas.
        """
        from engine.stats import StatsResult  # evitar importacion circular en tests
        audit_data = self._stats_panel.emit_audit_data(result)
        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._current_user,
            accion="STATS_COMPUTED",
            filas_procesadas=result.total_rows,
            columnas=[cs.name for cs in result.columns],
            tipo_join=self._result.join_type if self._result else None,
            duracion_ms=result.duration_ms,
            extra=audit_data,
        ))

    # ------------------------------------------------------------------
    # Exportacion
    # ------------------------------------------------------------------

    def _on_export(self) -> None:
        if self._result is None or self._result.df is None:
            QMessageBox.warning(self, "Sin resultado", "No hay datos para exportar.")
            return

        # Exportar la copia de trabajo (con ediciones y borrados aplicados).
        df_to_export = (
            self._source_model.working_df
            if self._source_model is not None
            else self._result.df
        )

        if df_to_export.empty and self._result.row_count == 0:
            reply = QMessageBox.question(
                self,
                "Exportar resultado vacío",
                "El resultado no tiene filas. "
                "¿Querés exportar igual (el archivo tendrá solo los encabezados)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar resultado",
            "resultado_cruce.xlsx",
            "Archivos Excel (*.xlsx)",
        )
        if not path:
            return

        dest = Path(path)
        if not dest.suffix:
            dest = dest.with_suffix(".xlsx")

        overwrite = False
        if dest.exists():
            reply = QMessageBox.question(
                self,
                "El archivo ya existe",
                f"'{dest.name}' ya existe. ¿Querés reemplazarlo?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            overwrite = True

        # Construir un CrossResult temporal con la copia de trabajo para exportar.
        from data.models import CrossResult as _CR
        export_result = _CR(
            df=df_to_export,
            row_count=len(df_to_export),
            join_type=self._result.join_type,
            columns_used=self._result.columns_used,
            warnings=self._result.warnings,
            duration_ms=self._result.duration_ms,
            name=self._result.name,
        )

        try:
            outcome = self._exporter.export(export_result, dest, overwrite=overwrite)
            self._logger.log(AuditEntry(
                timestamp=make_timestamp(),
                usuario=self._current_user,
                accion="EXPORT",
                archivos=[{"nombre": dest.name, "etiqueta": "exportacion"}],
                filas_procesadas=outcome.rows_written,
            ))
            QMessageBox.information(
                self,
                "Exportación exitosa",
                f"El archivo se guardó correctamente:\n{dest}\n\n"
                f"Filas exportadas: {outcome.rows_written:,}",
            )
        except Exception as exc:
            self._logger.log(AuditEntry(
                timestamp=make_timestamp(),
                usuario=self._current_user,
                accion="ERROR",
                mensaje_error=str(exc),
            ))
            QMessageBox.critical(
                self,
                "No se pudo guardar el archivo",
                "Ocurrió un error al guardar. Verificá que:\n"
                "• El archivo no esté abierto en Excel.\n"
                "• Tenés permiso de escritura en la carpeta destino.\n\n"
                "Si el problema persiste, comunicate con el equipo de Sistemas.",
            )
