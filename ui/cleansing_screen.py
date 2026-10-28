"""
ui/cleansing_screen.py — Pantalla de limpieza de datos (Motor de Cleansing).

Pantalla opcional entre carga de archivos y configuracion del cruce.
El usuario puede agregar reglas de transformacion por columna, ver un
preview de hasta 5 filas y aplicar o saltar la limpieza.

Senales:
    cleansing_completed(list[FileEntry])  — datos limpios; avanzar a cruce
    skip_requested(list[FileEntry])       — datos originales; avanzar igual
    back_requested()                      — volver a pantalla de carga

Restriccion RN-019: ningun valor de celda se registra en el log de auditoria.
"""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from audit.logger import AuditLogger, make_timestamp
from data.models import AuditEntry, FileEntry
from engine.cleansing import (
    OPERACIONES_VALIDAS,
    CleansingRule,
    apply_all_rules,
    preview_rule,
)
from ui.login_screen import (
    COLOR_ERROR,
    COLOR_PRIMARY,
    COLOR_PRIMARY_LIGHT,
    COLOR_SUCCESS,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MID,
    COLOR_WARNING,
    STYLE_BTN_PRIMARY,
    STYLE_SCREEN_TITLE,
)

# ---------------------------------------------------------------------------
# Nombres legibles para las operaciones
# ---------------------------------------------------------------------------

_OP_LABELS: dict[str, str] = {
    "strip_spaces":        "Quitar espacios extras",
    "to_uppercase":        "Convertir a MAYUSCULAS",
    "to_lowercase":        "Convertir a minusculas",
    "capitalize":          "Primera letra mayuscula",
    "replace_literal":     "Reemplazar texto (literal)",
    "replace_regex":       "Reemplazar con regex",
    "remove_chars":        "Eliminar caracteres",
    "keep_only_digits":    "Solo digitos (0-9)",
    "normalize_date":      "Normalizar fecha",
    "fill_empty":          "Rellenar vacios",
    "pad_left":            "Completar con caracteres (pad)",
    # Nuevas operaciones DataFrame-level
    "drop_column":         "Eliminar columna",
    "filter_date_before":  "Filtrar fechas anteriores a",
    "filter_date_after":   "Filtrar fechas posteriores a",
    "filter_date_range":   "Filtrar rango de fechas",
}

# Orden de presentacion en el combo.
_OP_ORDER: list[str] = [
    "strip_spaces",
    "to_uppercase",
    "to_lowercase",
    "capitalize",
    "replace_literal",
    "replace_regex",
    "remove_chars",
    "keep_only_digits",
    "normalize_date",
    "fill_empty",
    "pad_left",
    "drop_column",
    "filter_date_before",
    "filter_date_after",
    "filter_date_range",
]

# Formatos de fecha para los combos de normalize_date.
_DATE_FORMATS: list[str] = [
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%m/%d/%Y",
    "%d/%m/%y",
    "%Y%m%d",
]

# Estilo para campo de parametro de regla.
_STYLE_PARAM_INPUT = (
    f"border: 1.5px solid #ccd6e0; border-radius: 4px; "
    f"padding: 2px 6px; color: {COLOR_TEXT_DARK}; font-size: 11px;"
)


# ---------------------------------------------------------------------------
# Widget de parametros dinamicos segun la operacion
# ---------------------------------------------------------------------------

class ParamsWidget(QWidget):
    """
    Widget de parametros dinamicos. Internamente usa un QStackedWidget
    con una pagina por operacion que necesita parametros.
    Las operaciones sin parametros muestran una pagina vacia.
    """

    # Indice de paginas del stack interno.
    _PAGE_EMPTY = 0
    _PAGE_REPLACE_LITERAL = 1
    _PAGE_REPLACE_REGEX = 2
    _PAGE_REMOVE_CHARS = 3
    _PAGE_NORMALIZE_DATE = 4
    _PAGE_FILL_EMPTY = 5
    _PAGE_PAD_LEFT = 6
    _PAGE_FILTER_DATE_SINGLE = 7   # filter_date_before / filter_date_after
    _PAGE_FILTER_DATE_RANGE = 8    # filter_date_range

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Pagina 0: sin parametros.
        self._stack.addWidget(QWidget())

        # Pagina 1: replace_literal — buscar / reemplazar.
        self._stack.addWidget(self._make_replace_page(is_regex=False))

        # Pagina 2: replace_regex — buscar / reemplazar.
        self._stack.addWidget(self._make_replace_page(is_regex=True))

        # Pagina 3: remove_chars.
        p3 = QWidget()
        l3 = QHBoxLayout(p3)
        l3.setContentsMargins(0, 0, 0, 0)
        l3.setSpacing(4)
        lbl3 = QLabel("Caracteres a eliminar:")
        lbl3.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        l3.addWidget(lbl3)
        self._input_remove_chars = QLineEdit()
        self._input_remove_chars.setPlaceholderText('Ej: -.')
        self._input_remove_chars.setMinimumWidth(80)
        self._input_remove_chars.setMaximumWidth(120)
        self._input_remove_chars.setStyleSheet(_STYLE_PARAM_INPUT)
        l3.addWidget(self._input_remove_chars)
        l3.addStretch()
        self._stack.addWidget(p3)

        # Pagina 4: normalize_date — formato origen / destino.
        p4 = QWidget()
        l4 = QHBoxLayout(p4)
        l4.setContentsMargins(0, 0, 0, 0)
        l4.setSpacing(4)
        lbl4a = QLabel("De:")
        lbl4a.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        l4.addWidget(lbl4a)
        self._combo_date_from = QComboBox()
        self._combo_date_from.addItems(_DATE_FORMATS)
        self._combo_date_from.setEditable(True)
        self._combo_date_from.setMinimumWidth(110)
        l4.addWidget(self._combo_date_from)
        lbl4b = QLabel("A:")
        lbl4b.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        l4.addWidget(lbl4b)
        self._combo_date_to = QComboBox()
        self._combo_date_to.addItems(_DATE_FORMATS)
        self._combo_date_to.setEditable(True)
        self._combo_date_to.setCurrentIndex(1)   # default: %Y-%m-%d
        self._combo_date_to.setMinimumWidth(110)
        l4.addWidget(self._combo_date_to)
        l4.addStretch()
        self._stack.addWidget(p4)

        # Pagina 5: fill_empty.
        p5 = QWidget()
        l5 = QHBoxLayout(p5)
        l5.setContentsMargins(0, 0, 0, 0)
        l5.setSpacing(4)
        lbl5 = QLabel("Valor por defecto:")
        lbl5.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        l5.addWidget(lbl5)
        self._input_fill_empty = QLineEdit()
        self._input_fill_empty.setPlaceholderText('Ej: 0')
        self._input_fill_empty.setMinimumWidth(80)
        self._input_fill_empty.setMaximumWidth(140)
        self._input_fill_empty.setStyleSheet(_STYLE_PARAM_INPUT)
        l5.addWidget(self._input_fill_empty)
        l5.addStretch()
        self._stack.addWidget(p5)

        # Pagina 6: pad_left — ancho + caracter.
        p6 = QWidget()
        l6 = QHBoxLayout(p6)
        l6.setContentsMargins(0, 0, 0, 0)
        l6.setSpacing(4)
        lbl6a = QLabel("Ancho:")
        lbl6a.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        l6.addWidget(lbl6a)
        self._spin_pad_width = QSpinBox()
        self._spin_pad_width.setRange(1, 50)
        self._spin_pad_width.setValue(11)
        self._spin_pad_width.setFixedWidth(56)
        l6.addWidget(self._spin_pad_width)
        lbl6b = QLabel("Caracter:")
        lbl6b.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        l6.addWidget(lbl6b)
        self._input_pad_char = QLineEdit("0")
        self._input_pad_char.setMaxLength(1)
        self._input_pad_char.setFixedWidth(32)
        self._input_pad_char.setStyleSheet(_STYLE_PARAM_INPUT)
        l6.addWidget(self._input_pad_char)
        l6.addStretch()
        self._stack.addWidget(p6)

        # Pagina 7: filter_date_before / filter_date_after — una sola fecha.
        p7 = QWidget()
        l7 = QHBoxLayout(p7)
        l7.setContentsMargins(0, 0, 0, 0)
        l7.setSpacing(4)
        lbl7 = QLabel("Fecha limite:")
        lbl7.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        l7.addWidget(lbl7)
        self._input_date_single = QDateEdit()
        self._input_date_single.setCalendarPopup(True)
        self._input_date_single.setDisplayFormat("dd/MM/yyyy")
        self._input_date_single.setDate(QDate.currentDate())
        self._input_date_single.setMinimumWidth(130)
        self._input_date_single.setMaximumWidth(160)
        l7.addWidget(self._input_date_single)
        l7.addStretch()
        self._stack.addWidget(p7)

        # Pagina 8: filter_date_range — rango de fechas.
        p8 = QWidget()
        l8 = QHBoxLayout(p8)
        l8.setContentsMargins(0, 0, 0, 0)
        l8.setSpacing(4)
        lbl8a = QLabel("Desde:")
        lbl8a.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        l8.addWidget(lbl8a)
        self._input_date_from = QDateEdit()
        self._input_date_from.setCalendarPopup(True)
        self._input_date_from.setDisplayFormat("dd/MM/yyyy")
        self._input_date_from.setDate(QDate.currentDate())
        self._input_date_from.setMinimumWidth(120)
        self._input_date_from.setMaximumWidth(150)
        l8.addWidget(self._input_date_from)
        lbl8b = QLabel("Hasta:")
        lbl8b.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        l8.addWidget(lbl8b)
        self._input_date_to = QDateEdit()
        self._input_date_to.setCalendarPopup(True)
        self._input_date_to.setDisplayFormat("dd/MM/yyyy")
        self._input_date_to.setDate(QDate.currentDate())
        self._input_date_to.setMinimumWidth(120)
        self._input_date_to.setMaximumWidth(150)
        l8.addWidget(self._input_date_to)
        l8.addStretch()
        self._stack.addWidget(p8)

    def _make_replace_page(self, is_regex: bool) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        lbl_find = QLabel("Buscar:")
        lbl_find.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        layout.addWidget(lbl_find)

        input_find = QLineEdit()
        input_find.setPlaceholderText("patron" if is_regex else "texto")
        input_find.setMinimumWidth(100)
        input_find.setMaximumWidth(160)
        input_find.setStyleSheet(_STYLE_PARAM_INPUT)
        layout.addWidget(input_find)

        lbl_repl = QLabel("Reemplazar con:")
        lbl_repl.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        layout.addWidget(lbl_repl)

        input_repl = QLineEdit()
        input_repl.setPlaceholderText("(vacio = eliminar)")
        input_repl.setMinimumWidth(100)
        input_repl.setMaximumWidth(160)
        input_repl.setStyleSheet(_STYLE_PARAM_INPUT)
        layout.addWidget(input_repl)
        layout.addStretch()

        # Guardar referencias para get_params.
        if is_regex:
            self._input_regex_find = input_find
            self._input_regex_repl = input_repl
        else:
            self._input_literal_find = input_find
            self._input_literal_repl = input_repl

        return page

    def set_operation(self, op: str) -> None:
        """Muestra la pagina de parametros correspondiente a la operacion."""
        page_map = {
            "replace_literal":   self._PAGE_REPLACE_LITERAL,
            "replace_regex":     self._PAGE_REPLACE_REGEX,
            "remove_chars":      self._PAGE_REMOVE_CHARS,
            "normalize_date":    self._PAGE_NORMALIZE_DATE,
            "fill_empty":        self._PAGE_FILL_EMPTY,
            "pad_left":          self._PAGE_PAD_LEFT,
            # drop_column: sin parametros (pagina vacia)
            "drop_column":       self._PAGE_EMPTY,
            "filter_date_before": self._PAGE_FILTER_DATE_SINGLE,
            "filter_date_after":  self._PAGE_FILTER_DATE_SINGLE,
            "filter_date_range":  self._PAGE_FILTER_DATE_RANGE,
        }
        self._stack.setCurrentIndex(page_map.get(op, self._PAGE_EMPTY))

    def get_params(self, op: str) -> dict:
        """Retorna el dict de parametros para la operacion actual."""
        if op == "replace_literal":
            return {
                "find":    self._input_literal_find.text(),
                "replace": self._input_literal_repl.text(),
            }
        if op == "replace_regex":
            return {
                "pattern": self._input_regex_find.text(),
                "replace": self._input_regex_repl.text(),
            }
        if op == "remove_chars":
            return {"chars": self._input_remove_chars.text()}
        if op == "normalize_date":
            return {
                "format_from": self._combo_date_from.currentText(),
                "format_to":   self._combo_date_to.currentText(),
            }
        if op == "fill_empty":
            return {"value": self._input_fill_empty.text()}
        if op == "pad_left":
            char = self._input_pad_char.text()
            return {
                "width": self._spin_pad_width.value(),
                "char":  char if char else "0",
            }
        if op == "drop_column":
            return {}
        if op in ("filter_date_before", "filter_date_after"):
            return {"date": self._input_date_single.date().toString("dd/MM/yyyy")}
        if op == "filter_date_range":
            return {
                "date_from": self._input_date_from.date().toString("dd/MM/yyyy"),
                "date_to":   self._input_date_to.date().toString("dd/MM/yyyy"),
            }
        return {}

    def set_params(self, op: str, params: dict) -> None:
        """Precarga valores de parametros (para presets)."""
        if op == "replace_literal":
            self._input_literal_find.setText(str(params.get("find", "")))
            self._input_literal_repl.setText(str(params.get("replace", "")))
        elif op == "replace_regex":
            self._input_regex_find.setText(str(params.get("pattern", "")))
            self._input_regex_repl.setText(str(params.get("replace", "")))
        elif op == "remove_chars":
            self._input_remove_chars.setText(str(params.get("chars", "")))
        elif op == "normalize_date":
            fmt_from = params.get("format_from", "%d/%m/%Y")
            fmt_to = params.get("format_to", "%Y-%m-%d")
            idx_from = self._combo_date_from.findText(fmt_from)
            if idx_from >= 0:
                self._combo_date_from.setCurrentIndex(idx_from)
            else:
                self._combo_date_from.setCurrentText(fmt_from)
            idx_to = self._combo_date_to.findText(fmt_to)
            if idx_to >= 0:
                self._combo_date_to.setCurrentIndex(idx_to)
            else:
                self._combo_date_to.setCurrentText(fmt_to)
        elif op == "fill_empty":
            self._input_fill_empty.setText(str(params.get("value", "")))
        elif op == "pad_left":
            self._spin_pad_width.setValue(int(params.get("width", 11)))
            self._input_pad_char.setText(str(params.get("char", "0")))
        elif op in ("filter_date_before", "filter_date_after"):
            date_str = str(params.get("date", ""))
            if date_str:
                qdate = QDate.fromString(date_str, "dd/MM/yyyy")
                if qdate.isValid():
                    self._input_date_single.setDate(qdate)
        elif op == "filter_date_range":
            from_str = str(params.get("date_from", ""))
            to_str = str(params.get("date_to", ""))
            if from_str:
                qd = QDate.fromString(from_str, "dd/MM/yyyy")
                if qd.isValid():
                    self._input_date_from.setDate(qd)
            if to_str:
                qd = QDate.fromString(to_str, "dd/MM/yyyy")
                if qd.isValid():
                    self._input_date_to.setDate(qd)


# ---------------------------------------------------------------------------
# Fila de regla
# ---------------------------------------------------------------------------

class RuleRow(QWidget):
    """
    Una fila de regla: [archivo] [columna] [operacion] [params] [✕]
    Emite changed() cada vez que cualquier campo cambia (para actualizar preview).
    Emite removed(self) cuando el usuario presiona ✕.
    """

    changed = Signal()
    removed = Signal(object)  # emite self

    def __init__(
        self,
        file_entries: list[FileEntry],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._file_entries = file_entries

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(6)

        # --- Selector de archivo ---
        self._combo_file = QComboBox()
        self._combo_file.setMinimumWidth(130)
        self._combo_file.setMaximumWidth(160)
        for e in file_entries:
            self._combo_file.addItem(e.label)
        layout.addWidget(self._combo_file)

        # --- Selector de columna ---
        self._combo_col = QComboBox()
        self._combo_col.setMinimumWidth(130)
        self._combo_col.setMaximumWidth(180)
        layout.addWidget(self._combo_col)

        # --- Selector de operacion ---
        self._combo_op = QComboBox()
        self._combo_op.setMinimumWidth(160)
        self._combo_op.setMaximumWidth(200)
        for op in _OP_ORDER:
            self._combo_op.addItem(_OP_LABELS[op], userData=op)
        layout.addWidget(self._combo_op)

        # --- Parametros dinamicos ---
        self._params_widget = ParamsWidget()
        self._params_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._params_widget)

        # --- Boton quitar ---
        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(30)
        btn_remove.setFixedHeight(28)
        btn_remove.setStyleSheet(
            f"color: {COLOR_ERROR}; font-weight: bold; font-size: 13px; "
            f"border: 1.5px solid {COLOR_ERROR}; border-radius: 4px; background: white;"
        )
        btn_remove.setToolTip("Quitar esta regla")
        btn_remove.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(btn_remove)

        # Inicializar columnas segun archivo seleccionado.
        self._refresh_columns()

        # Conectar senales.
        self._combo_file.currentIndexChanged.connect(self._on_file_changed)
        self._combo_col.currentIndexChanged.connect(self.changed)
        self._combo_op.currentIndexChanged.connect(self._on_op_changed)

    # ------------------------------------------------------------------
    # Actualizacion interna
    # ------------------------------------------------------------------

    def _refresh_columns(self) -> None:
        idx = self._combo_file.currentIndex()
        if idx < 0 or idx >= len(self._file_entries):
            self._combo_col.clear()
            return
        entry = self._file_entries[idx]
        prev_col = self._combo_col.currentText()
        self._combo_col.blockSignals(True)
        self._combo_col.clear()
        self._combo_col.addItems(entry.metadata.column_names)
        # Intentar restaurar la seleccion anterior.
        idx_col = self._combo_col.findText(prev_col)
        if idx_col >= 0:
            self._combo_col.setCurrentIndex(idx_col)
        self._combo_col.blockSignals(False)

    def _on_file_changed(self) -> None:
        self._refresh_columns()
        self.changed.emit()

    def _on_op_changed(self) -> None:
        op = self._combo_op.currentData()
        self._params_widget.set_operation(op)
        self.changed.emit()

    # ------------------------------------------------------------------
    # Interfaz publica
    # ------------------------------------------------------------------

    def get_rule(self) -> CleansingRule:
        """Construye y retorna la CleansingRule actual."""
        file_label = self._combo_file.currentText()
        column = self._combo_col.currentText()
        op = self._combo_op.currentData()
        params = self._params_widget.get_params(op)
        return CleansingRule.new(
            file_label=file_label,
            column=column,
            operation=op,
            params=params,
        )

    def preset(self, file_label: str, column: str, op: str, params: dict) -> None:
        """
        Precarga valores desde un preset.
        Selecciona el archivo, la columna y la operacion dados.
        """
        idx_file = self._combo_file.findText(file_label)
        if idx_file >= 0:
            self._combo_file.setCurrentIndex(idx_file)
        # Actualizar columnas antes de seleccionar.
        self._refresh_columns()
        idx_col = self._combo_col.findText(column)
        if idx_col >= 0:
            self._combo_col.setCurrentIndex(idx_col)
        idx_op = self._combo_op.findData(op)
        if idx_op >= 0:
            self._combo_op.setCurrentIndex(idx_op)
        self._params_widget.set_operation(op)
        self._params_widget.set_params(op, params)


# ---------------------------------------------------------------------------
# Panel de preview
# ---------------------------------------------------------------------------

class PreviewPanel(QWidget):
    """
    Muestra hasta 5 pares (antes → despues) para la regla seleccionada.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        lbl_title = QLabel("Vista previa de la transformacion")
        lbl_title.setStyleSheet(
            f"font-weight: bold; color: {COLOR_PRIMARY}; font-size: 12px;"
        )
        layout.addWidget(lbl_title)

        self._error_lbl = QLabel("")
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setStyleSheet(
            f"color: {COLOR_ERROR}; font-size: 11px; "
            f"background-color: #fdecea; border-radius: 4px; padding: 4px 8px;"
        )
        self._error_lbl.hide()
        layout.addWidget(self._error_lbl)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Antes", "Despues"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(110)
        self._table.setMaximumHeight(160)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setStyleSheet(
            "font-size: 11px; "
            "QHeaderView::section { background-color: #e8eef6; "
            f"  color: {COLOR_PRIMARY}; font-weight: bold; padding: 3px; }}"
        )
        layout.addWidget(self._table)

        self._lbl_empty = QLabel("(ninguna regla seleccionada o columna vacia)")
        self._lbl_empty.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px; font-style: italic;")
        layout.addWidget(self._lbl_empty)

    def update_preview(
        self,
        pairs: list[tuple[str, str]],
        error_msg: str = "",
    ) -> None:
        self._table.setRowCount(0)
        self._error_lbl.hide()
        self._lbl_empty.hide()

        if error_msg:
            self._error_lbl.setText(error_msg)
            self._error_lbl.show()
            return

        if not pairs:
            self._lbl_empty.show()
            return

        for before, after in pairs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(before))
            item_after = QTableWidgetItem(after)
            # Colorear verde si cambio, gris si no.
            if before != after:
                item_after.setForeground(Qt.GlobalColor.darkGreen)
            self._table.setItem(row, 1, item_after)


# ---------------------------------------------------------------------------
# Pantalla principal
# ---------------------------------------------------------------------------

class CleansingScreen(QWidget):
    """
    Pantalla de limpieza de datos (opcional).
    Se inserta entre LoadScreen y CrossScreen.
    """

    cleansing_completed = Signal(list)   # list[FileEntry] limpios
    skip_requested      = Signal(list)   # list[FileEntry] originales
    back_requested      = Signal()

    def __init__(self, audit_logger: AuditLogger, parent=None) -> None:
        super().__init__(parent)
        self._logger = audit_logger
        self._file_entries: list[FileEntry] = []
        self._current_user: str = ""
        self._rule_rows: list[RuleRow] = []

        self._build_ui()

    # ------------------------------------------------------------------
    # Construccion de UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(24, 16, 24, 16)
        main.setSpacing(12)

        # --- Encabezado ---
        header = QLabel("Limpieza de datos (opcional)")
        header.setStyleSheet(STYLE_SCREEN_TITLE)
        main.addWidget(header)

        desc = QLabel(
            "Antes de cruzar los archivos podés normalizar columnas: "
            "eliminar espacios, unificar formatos de fecha, completar ceros a la izquierda, etc. "
            "Si no necesitas limpiar nada, usa <b>Saltar limpieza</b>."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 12px;")
        main.addWidget(desc)

        # --- Encabezado de columnas ---
        col_header = QFrame()
        col_header.setStyleSheet(
            f"background-color: {COLOR_PRIMARY}; border-radius: 4px;"
        )
        col_hl = QHBoxLayout(col_header)
        col_hl.setContentsMargins(8, 4, 8, 4)
        col_hl.setSpacing(0)
        for label, width in [
            ("Archivo", 148),
            ("Columna", 188),
            ("Operacion", 208),
            ("Parametros", 0),
        ]:
            lbl = QLabel(label)
            if width:
                lbl.setMinimumWidth(width)
                lbl.setMaximumWidth(width)
            lbl.setStyleSheet(
                "color: white; font-weight: bold; font-size: 11px; background: transparent;"
            )
            col_hl.addWidget(lbl)
        col_hl.addStretch()
        main.addWidget(col_header)

        # --- Area de scroll para reglas ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: #f9fbfd;")

        self._rules_container = QWidget()
        self._rules_container.setStyleSheet("background-color: #f9fbfd;")
        self._rules_layout = QVBoxLayout(self._rules_container)
        self._rules_layout.setSpacing(2)
        self._rules_layout.setContentsMargins(4, 4, 4, 4)
        self._rules_layout.addStretch()

        scroll.setWidget(self._rules_container)
        main.addWidget(scroll, 1)

        # --- Fila de botones de agregar + presets ---
        add_row = QHBoxLayout()

        btn_add = QPushButton("＋  Agregar regla")
        btn_add.setMinimumHeight(34)
        btn_add.setStyleSheet(
            f"color: {COLOR_PRIMARY}; border: 1.5px solid {COLOR_PRIMARY}; "
            f"border-radius: 4px; font-weight: bold; padding: 4px 14px;"
        )
        btn_add.clicked.connect(self._add_rule_row)
        add_row.addWidget(btn_add)

        btn_preset = QPushButton("Presets  ▼")
        btn_preset.setMinimumHeight(34)
        btn_preset.setStyleSheet(
            f"color: {COLOR_PRIMARY}; border: 1.5px solid {COLOR_PRIMARY}; "
            f"border-radius: 4px; font-weight: bold; padding: 4px 14px;"
        )
        btn_preset.clicked.connect(self._show_preset_menu)
        add_row.addWidget(btn_preset)

        add_row.addStretch()
        main.addLayout(add_row)

        # --- Panel de preview ---
        preview_frame = QFrame()
        preview_frame.setStyleSheet(
            f"background-color: {COLOR_PRIMARY_LIGHT}; border-radius: 6px; padding: 2px;"
        )
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(12, 8, 12, 8)
        self._preview_panel = PreviewPanel()
        preview_layout.addWidget(self._preview_panel)
        main.addWidget(preview_frame)

        # --- Botones de navegacion ---
        btn_row = QHBoxLayout()

        self._btn_back = QPushButton("← Volver a carga")
        self._btn_back.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #ccd6e0; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        self._btn_back.clicked.connect(self.back_requested)
        btn_row.addWidget(self._btn_back)

        btn_row.addStretch()

        self._btn_skip = QPushButton("Saltar limpieza →")
        self._btn_skip.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #aaa; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        self._btn_skip.clicked.connect(self._on_skip)
        btn_row.addWidget(self._btn_skip)

        self._btn_apply = QPushButton("Aplicar y continuar →")
        self._btn_apply.setMinimumHeight(42)
        self._btn_apply.setStyleSheet(
            f"background-color: {COLOR_SUCCESS}; color: white; "
            f"font-weight: bold; border-radius: 5px; padding: 6px 18px; font-size: 13px;"
        )
        self._btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(self._btn_apply)

        main.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Carga de archivos desde main_window
    # ------------------------------------------------------------------

    def load_files(self, file_entries: list[FileEntry], current_user: str = "") -> None:
        """Inicializa la pantalla con los archivos confirmados."""
        self._file_entries = file_entries
        self._current_user = current_user

        # Limpiar reglas anteriores.
        for row in self._rule_rows[:]:
            self._rules_layout.removeWidget(row)
            row.deleteLater()
        self._rule_rows.clear()

        # Limpiar preview.
        self._preview_panel.update_preview([])

    def load_recipe_rules(self, rules: list[CleansingRule]) -> None:
        """
        Limpia las reglas actuales y carga las de la receta.
        Cada regla se agrega como una fila preconfigurada.
        Si el archivo o la columna de la regla no coincide con los archivos
        actuales, la fila se agrega igualmente con los valores disponibles
        para que el usuario pueda ajustarla.
        """
        # Limpiar filas actuales.
        for row in self._rule_rows[:]:
            self._rules_layout.removeWidget(row)
            row.deleteLater()
        self._rule_rows.clear()
        self._preview_panel.update_preview([])

        for rule in rules:
            self._add_rule_row(
                file_label=rule.file_label,
                column=rule.column,
                op=rule.operation,
                params=rule.params,
            )

    # ------------------------------------------------------------------
    # Gestion de filas de regla
    # ------------------------------------------------------------------

    def _add_rule_row(self, file_label: str = "", column: str = "",
                      op: str = "", params: dict | None = None) -> RuleRow:
        if not self._file_entries:
            QMessageBox.information(
                self,
                "Sin archivos",
                "No hay archivos cargados. Volvé a la pantalla de carga.",
            )
            return None  # type: ignore[return-value]

        row = RuleRow(file_entries=self._file_entries)
        row.changed.connect(lambda: self._on_rule_changed(row))
        row.removed.connect(self._remove_rule_row)
        self._rule_rows.append(row)
        self._rules_layout.insertWidget(self._rules_layout.count() - 1, row)

        # Precargar valores si vienen de un preset.
        if op:
            row.preset(
                file_label=file_label or (self._file_entries[0].label if self._file_entries else ""),
                column=column,
                op=op,
                params=params or {},
            )
        return row

    def _remove_rule_row(self, row: RuleRow) -> None:
        if row in self._rule_rows:
            self._rule_rows.remove(row)
        self._rules_layout.removeWidget(row)
        row.deleteLater()
        # Limpiar preview si ya no hay filas.
        if not self._rule_rows:
            self._preview_panel.update_preview([])

    def _on_rule_changed(self, row: RuleRow) -> None:
        """Actualiza el panel de preview cuando una regla cambia."""
        rule = row.get_rule()

        # Operaciones DataFrame-level: preview sintetico sin necesitar la serie.
        if rule.operation in ("drop_column", "filter_date_before",
                               "filter_date_after", "filter_date_range"):
            pairs = preview_rule(None, rule, n=5)  # type: ignore[arg-type]
            # preview_rule retorna [("mensaje", "")] para estas operaciones.
            self._preview_panel.update_preview(pairs)
            return

        # Buscar la serie correspondiente.
        entry = next((e for e in self._file_entries if e.label == rule.file_label), None)
        if entry is None or rule.column not in entry.df.columns:
            self._preview_panel.update_preview([])
            return

        series = entry.df[rule.column]
        # Detectar error de regex antes de llamar a preview_rule.
        if rule.operation == "replace_regex":
            import re
            pattern = rule.params.get("pattern", "")
            if not pattern:
                self._preview_panel.update_preview([])
                return
            try:
                re.compile(pattern)
            except re.error as exc:
                self._preview_panel.update_preview(
                    [],
                    error_msg=f"Expresion regular invalida: {exc}",
                )
                return

        pairs = preview_rule(series, rule, n=5)
        self._preview_panel.update_preview(pairs)

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    def _show_preset_menu(self) -> None:
        """Muestra un menu contextual con presets predefinidos."""
        btn = self.sender()
        menu = QMenu(self)

        menu.addAction(
            'Limpiar CUIL/CUIT (quitar - y .)',
            lambda: self._apply_preset("remove_chars", {"chars": "-."}),
        )
        menu.addAction(
            'Solo digitos (CUIL/DNI)',
            lambda: self._apply_preset("keep_only_digits", {}),
        )
        menu.addAction(
            'Fecha AR → ISO (dd/mm/aaaa → aaaa-mm-dd)',
            lambda: self._apply_preset(
                "normalize_date",
                {"format_from": "%d/%m/%Y", "format_to": "%Y-%m-%d"},
            ),
        )
        menu.addAction(
            'Quitar espacios extras',
            lambda: self._apply_preset("strip_spaces", {}),
        )

        if btn:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            menu.exec(self.cursor().pos())

    def _apply_preset(self, op: str, params: dict) -> None:
        """
        Agrega una nueva fila preconfigurada con el preset elegido.
        Usa el primer archivo y primera columna como valores iniciales;
        el usuario puede cambiarlos.
        """
        first_label = self._file_entries[0].label if self._file_entries else ""
        first_col = (
            self._file_entries[0].metadata.column_names[0]
            if self._file_entries and self._file_entries[0].metadata.column_names
            else ""
        )
        self._add_rule_row(
            file_label=first_label,
            column=first_col,
            op=op,
            params=params,
        )

    # ------------------------------------------------------------------
    # Acciones de navegacion
    # ------------------------------------------------------------------

    def _on_skip(self) -> None:
        """Emite skip_requested con los archivos originales sin modificar."""
        self.skip_requested.emit(list(self._file_entries))

    def _on_apply(self) -> None:
        """
        Valida todas las reglas, aplica la limpieza y emite cleansing_completed.
        Si no hay reglas, comportamiento equivalente a saltar.
        """
        if not self._rule_rows:
            self.cleansing_completed.emit(list(self._file_entries))
            return

        # Validar reglas de regex antes de aplicar.
        import re
        for row in self._rule_rows:
            rule = row.get_rule()
            if rule.operation == "replace_regex":
                pattern = rule.params.get("pattern", "")
                if pattern:
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        QMessageBox.warning(
                            self,
                            "Expresion regular invalida",
                            f"La regla sobre '{rule.column}' tiene un patron invalido:\n\n"
                            f"{exc}\n\n"
                            "Corregilo antes de continuar.",
                        )
                        return

        rules = [row.get_rule() for row in self._rule_rows]
        clean_entries = apply_all_rules(self._file_entries, rules)

        # Registro de auditoria — SIN valores de celdas (RN-019).
        affected_labels = list({r.file_label for r in rules})
        affected_cols   = list({r.column for r in rules})
        total_rows = sum(
            e.metadata.row_count
            for e in self._file_entries
            if e.label in affected_labels
        )
        ops_used = list({r.operation for r in rules})

        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._current_user,
            accion="CLEANSING_APPLY",
            archivos=[{"etiqueta": lbl} for lbl in affected_labels],
            columnas=affected_cols,
            filas_procesadas=total_rows,
            extra={
                "operaciones": ops_used,
                "reglas_count": len(rules),
            },
        ))

        self.cleansing_completed.emit(clean_entries)
