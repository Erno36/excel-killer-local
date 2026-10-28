"""
ui/rules_screen.py — Pantalla de reglas de negocio (paso opcional).

Permite crear columnas calculadas con logica condicional sobre el resultado
del cruce, sin escribir codigo.

Tipos soportados:
  - if_then_else : SI condicion(es) ENTONCES valor_A SINO valor_B
  - formula      : columna/literal  operador  columna/literal
  - date_diff    : diferencia entre dos columnas de fecha en dias/meses/anos

RN-019: el log de auditoria NO contiene value_true, value_false, literales
de formulas ni valores de celdas. Solo registra nombres de columna destino
y conteos.
"""
from __future__ import annotations

from dataclasses import replace as dc_replace

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import pandas as pd

from audit.logger import AuditLogger, make_timestamp
from data.models import AuditEntry, BusinessRule, CrossResult, RuleCondition
from engine.rules_engine import apply_all_rules, apply_rule, preview_rule
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

# ---------------------------------------------------------------------------
# Constantes de presentacion
# ---------------------------------------------------------------------------

_RULE_TYPE_LABELS = {
    "if_then_else": "SI / ENTONCES / SINO",
    "formula": "Formula",
    "date_diff": "Diferencia de fechas",
}

_CONDITION_OPERATOR_LABELS = [
    ("==",         "igual a"),
    ("!=",         "distinto de"),
    ("<",          "menor que"),
    ("<=",         "menor o igual"),
    (">",          "mayor que"),
    (">=",         "mayor o igual"),
    ("contiene",   "contiene"),
    ("es_vacio",   "es vacio"),
    ("no_es_vacio","no es vacio"),
]

_FORMULA_OPERATOR_LABELS = [
    ("+", "+"),
    ("-", "−"),
    ("*", "×"),
    ("/", "÷"),
]

_UNIT_LABELS = [
    ("days",   "Dias"),
    ("months", "Meses"),
    ("years",  "Anos"),
]

_OPS_SIN_VALOR = frozenset({"es_vacio", "no_es_vacio"})

_COLOR_PREVIEW_ERROR = "#e67e22"  # naranja para errores de configuracion


# ---------------------------------------------------------------------------
# Widget: condicion individual (fila dentro del editor if_then_else)
# ---------------------------------------------------------------------------

class ConditionRow(QWidget):
    """Una condicion: [columna] [operador] [valor] [✕]."""

    removed = Signal(object)  # emite self

    def __init__(
        self,
        columns: list[str],
        removable: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._columns = columns
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self._combo_col = QComboBox()
        self._combo_col.addItems(columns)
        self._combo_col.setMinimumWidth(140)
        layout.addWidget(self._combo_col)

        self._combo_op = QComboBox()
        for key, label in _CONDITION_OPERATOR_LABELS:
            self._combo_op.addItem(label, key)
        self._combo_op.setMinimumWidth(120)
        self._combo_op.currentIndexChanged.connect(self._on_op_changed)
        layout.addWidget(self._combo_op)

        self._input_val = QLineEdit()
        self._input_val.setPlaceholderText("Valor...")
        self._input_val.setMinimumWidth(120)
        self._input_val.setStyleSheet(
            f"border: 1px solid #ccd6e0; border-radius: 4px; "
            f"padding: 3px 8px; font-size: 12px; color: {COLOR_TEXT_DARK};"
        )
        layout.addWidget(self._input_val)
        layout.addStretch()

        btn_rm = QPushButton("✕")
        btn_rm.setFixedWidth(28)
        btn_rm.setFixedHeight(26)
        btn_rm.setStyleSheet(
            f"color: {COLOR_ERROR}; font-weight: bold; font-size: 12px; "
            f"border: 1.5px solid {COLOR_ERROR}; border-radius: 4px; background: white;"
        )
        btn_rm.setVisible(removable)
        btn_rm.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(btn_rm)

    def _on_op_changed(self) -> None:
        op = self._combo_op.currentData()
        needs_val = op not in _OPS_SIN_VALOR
        self._input_val.setEnabled(needs_val)
        if not needs_val:
            self._input_val.clear()

    def get_condition_dict(self) -> dict:
        return {
            "column": self._combo_col.currentText(),
            "operator": self._combo_op.currentData(),
            "value": self._input_val.text().strip(),
        }

    def connected_widgets(self) -> list[QWidget]:
        """Widgets cuyo cambio debe disparar el preview."""
        return [self._combo_col, self._combo_op, self._input_val]


# ---------------------------------------------------------------------------
# Widget: editor de parametros segun tipo de regla
# ---------------------------------------------------------------------------

class RuleParamsWidget(QWidget):
    """
    Contenedor que muestra el editor de parametros correcto segun rule_type.
    Emite params_changed() cuando cualquier campo cambia.
    """

    params_changed = Signal()

    def __init__(self, columns: list[str], parent=None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._current_type: str = "if_then_else"

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(6)

        # -- Panel if_then_else --
        self._panel_ifthen = self._build_ifthen_panel()
        self._outer.addWidget(self._panel_ifthen)

        # -- Panel formula --
        self._panel_formula = self._build_formula_panel()
        self._panel_formula.hide()
        self._outer.addWidget(self._panel_formula)

        # -- Panel date_diff --
        self._panel_datediff = self._build_datediff_panel()
        self._panel_datediff.hide()
        self._outer.addWidget(self._panel_datediff)

    # ------------------------------------------------------------------ #
    # Construccion de paneles                                             #
    # ------------------------------------------------------------------ #

    def _build_ifthen_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lbl = QLabel("Condiciones:")
        lbl.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {COLOR_TEXT_DARK};")
        lay.addWidget(lbl)

        self._conditions_container = QWidget()
        self._conditions_layout = QVBoxLayout(self._conditions_container)
        self._conditions_layout.setContentsMargins(0, 0, 0, 0)
        self._conditions_layout.setSpacing(2)
        lay.addWidget(self._conditions_container)

        self._condition_rows: list[ConditionRow] = []
        self._add_condition_row(removable=False)

        add_comb_row = QHBoxLayout()
        btn_add_cond = QPushButton("+ Agregar condicion")
        btn_add_cond.setStyleSheet(
            f"color: {COLOR_PRIMARY}; border: 1px solid {COLOR_PRIMARY}; "
            f"border-radius: 4px; font-size: 11px; padding: 2px 8px;"
        )
        btn_add_cond.clicked.connect(lambda: self._add_condition_row(removable=True))
        add_comb_row.addWidget(btn_add_cond)
        add_comb_row.addSpacing(20)

        lbl_comb = QLabel("Combinar con:")
        lbl_comb.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        add_comb_row.addWidget(lbl_comb)

        self._radio_and = QRadioButton("AND")
        self._radio_and.setChecked(True)
        self._radio_and.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        self._radio_and.toggled.connect(lambda _: self.params_changed.emit())
        add_comb_row.addWidget(self._radio_and)

        self._radio_or = QRadioButton("OR")
        self._radio_or.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        add_comb_row.addWidget(self._radio_or)
        add_comb_row.addStretch()
        lay.addLayout(add_comb_row)

        val_row = QHBoxLayout()
        lbl_true = QLabel("Valor si SE CUMPLE:")
        lbl_true.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        lbl_true.setMinimumWidth(160)
        val_row.addWidget(lbl_true)

        self._input_value_true = QLineEdit()
        self._input_value_true.setPlaceholderText("Ej: CAT")
        self._input_value_true.setMinimumWidth(140)
        self._input_value_true.setStyleSheet(
            f"border: 1px solid #ccd6e0; border-radius: 4px; "
            f"padding: 3px 8px; font-size: 12px; color: {COLOR_TEXT_DARK};"
        )
        self._input_value_true.textChanged.connect(lambda _: self.params_changed.emit())
        val_row.addWidget(self._input_value_true)
        val_row.addStretch()
        lay.addLayout(val_row)

        val_false_row = QHBoxLayout()
        lbl_false = QLabel("Valor si NO se cumple:")
        lbl_false.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        lbl_false.setMinimumWidth(160)
        val_false_row.addWidget(lbl_false)

        self._input_value_false = QLineEdit()
        self._input_value_false.setPlaceholderText("Ej: Sucursal")
        self._input_value_false.setMinimumWidth(140)
        self._input_value_false.setStyleSheet(
            f"border: 1px solid #ccd6e0; border-radius: 4px; "
            f"padding: 3px 8px; font-size: 12px; color: {COLOR_TEXT_DARK};"
        )
        self._input_value_false.textChanged.connect(lambda _: self.params_changed.emit())
        val_false_row.addWidget(self._input_value_false)
        val_false_row.addStretch()
        lay.addLayout(val_false_row)

        return w

    def _build_formula_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        formula_row = QHBoxLayout()

        self._combo_left = QComboBox()
        self._combo_left.setEditable(True)
        self._combo_left.addItems(self._columns)
        self._combo_left.setMinimumWidth(160)
        self._combo_left.setToolTip("Columna del resultado o numero literal (ej: 1000)")
        self._combo_left.currentTextChanged.connect(lambda _: self.params_changed.emit())
        formula_row.addWidget(self._combo_left)

        self._combo_formula_op = QComboBox()
        for key, label in _FORMULA_OPERATOR_LABELS:
            self._combo_formula_op.addItem(label, key)
        self._combo_formula_op.setFixedWidth(50)
        self._combo_formula_op.currentIndexChanged.connect(lambda _: self.params_changed.emit())
        formula_row.addWidget(self._combo_formula_op)

        self._combo_right = QComboBox()
        self._combo_right.setEditable(True)
        self._combo_right.addItems(self._columns)
        self._combo_right.setMinimumWidth(160)
        self._combo_right.setToolTip("Columna del resultado o numero literal (ej: 1000)")
        self._combo_right.currentTextChanged.connect(lambda _: self.params_changed.emit())
        formula_row.addWidget(self._combo_right)

        formula_row.addStretch()
        lay.addLayout(formula_row)

        fmt_row = QHBoxLayout()
        lbl_fmt = QLabel("Formato resultado:")
        lbl_fmt.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        fmt_row.addWidget(lbl_fmt)

        self._radio_fmt_number = QRadioButton("Numero")
        self._radio_fmt_number.setChecked(True)
        self._radio_fmt_number.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        self._radio_fmt_number.toggled.connect(lambda _: self.params_changed.emit())
        fmt_row.addWidget(self._radio_fmt_number)

        self._radio_fmt_text = QRadioButton("Texto")
        self._radio_fmt_text.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        fmt_row.addWidget(self._radio_fmt_text)
        fmt_row.addStretch()
        lay.addLayout(fmt_row)

        return w

    def _build_datediff_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        diff_row = QHBoxLayout()

        lbl_a = QLabel("Fecha A (minuendo):")
        lbl_a.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        diff_row.addWidget(lbl_a)

        self._combo_date_a = QComboBox()
        self._combo_date_a.addItems(self._columns)
        self._combo_date_a.setMinimumWidth(150)
        self._combo_date_a.currentIndexChanged.connect(lambda _: self.params_changed.emit())
        diff_row.addWidget(self._combo_date_a)

        lbl_minus = QLabel("  −  ")
        lbl_minus.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {COLOR_PRIMARY};")
        diff_row.addWidget(lbl_minus)

        lbl_b = QLabel("Fecha B (sustraendo):")
        lbl_b.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        diff_row.addWidget(lbl_b)

        self._combo_date_b = QComboBox()
        self._combo_date_b.addItems(self._columns)
        self._combo_date_b.setMinimumWidth(150)
        self._combo_date_b.currentIndexChanged.connect(lambda _: self.params_changed.emit())
        diff_row.addWidget(self._combo_date_b)

        diff_row.addStretch()
        lay.addLayout(diff_row)

        opts_row = QHBoxLayout()
        lbl_unit = QLabel("Unidad:")
        lbl_unit.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        opts_row.addWidget(lbl_unit)

        self._radio_days = QRadioButton("Dias")
        self._radio_days.setChecked(True)
        self._radio_days.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        self._radio_days.toggled.connect(lambda _: self.params_changed.emit())
        opts_row.addWidget(self._radio_days)

        self._radio_months = QRadioButton("Meses")
        self._radio_months.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        opts_row.addWidget(self._radio_months)

        self._radio_years = QRadioButton("Anos")
        self._radio_years.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        opts_row.addWidget(self._radio_years)

        opts_row.addSpacing(24)

        self._chk_absolute = QCheckBox("Siempre positivo")
        self._chk_absolute.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        self._chk_absolute.stateChanged.connect(lambda _: self.params_changed.emit())
        opts_row.addWidget(self._chk_absolute)
        opts_row.addStretch()
        lay.addLayout(opts_row)

        return w

    # ------------------------------------------------------------------ #
    # Gestion de condiciones (panel if_then_else)                         #
    # ------------------------------------------------------------------ #

    def _add_condition_row(self, removable: bool = True) -> None:
        row = ConditionRow(columns=self._columns, removable=removable)
        row.removed.connect(self._remove_condition_row)
        for w in row.connected_widgets():
            if hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(lambda _: self.params_changed.emit())
            elif hasattr(w, "textChanged"):
                w.textChanged.connect(lambda _: self.params_changed.emit())
        self._condition_rows.append(row)
        self._conditions_layout.addWidget(row)
        self.params_changed.emit()

    def _remove_condition_row(self, row: ConditionRow) -> None:
        if len(self._condition_rows) <= 1:
            return
        self._condition_rows.remove(row)
        self._conditions_layout.removeWidget(row)
        row.deleteLater()
        self.params_changed.emit()

    # ------------------------------------------------------------------ #
    # Cambio de tipo                                                      #
    # ------------------------------------------------------------------ #

    def set_rule_type(self, rule_type: str) -> None:
        self._current_type = rule_type
        self._panel_ifthen.setVisible(rule_type == "if_then_else")
        self._panel_formula.setVisible(rule_type == "formula")
        self._panel_datediff.setVisible(rule_type == "date_diff")
        self.params_changed.emit()

    # ------------------------------------------------------------------ #
    # Lectura de parametros                                               #
    # ------------------------------------------------------------------ #

    def get_params(self) -> dict:
        if self._current_type == "if_then_else":
            return {
                "conditions": [r.get_condition_dict() for r in self._condition_rows],
                "combinator": "AND" if self._radio_and.isChecked() else "OR",
                "value_true": self._input_value_true.text().strip(),
                "value_false": self._input_value_false.text().strip(),
            }
        elif self._current_type == "formula":
            return {
                "left": self._combo_left.currentText().strip(),
                "operator": self._combo_formula_op.currentData(),
                "right": self._combo_right.currentText().strip(),
                "format": "number" if self._radio_fmt_number.isChecked() else "text",
            }
        else:  # date_diff
            unit = "days"
            if self._radio_months.isChecked():
                unit = "months"
            elif self._radio_years.isChecked():
                unit = "years"
            return {
                "col_a": self._combo_date_a.currentText(),
                "col_b": self._combo_date_b.currentText(),
                "unit": unit,
                "absolute": self._chk_absolute.isChecked(),
            }

    def validate(self) -> str | None:
        """Retorna mensaje de error si la config esta incompleta, None si OK."""
        t = self._current_type
        if t == "if_then_else":
            if not self._condition_rows:
                return "Debes agregar al menos una condicion."
            for r in self._condition_rows:
                if not r.get_condition_dict()["column"]:
                    return "Selecciona una columna en cada condicion."
        elif t == "formula":
            if not self._combo_left.currentText().strip():
                return "El operando izquierdo no puede estar vacio."
            if not self._combo_right.currentText().strip():
                return "El operando derecho no puede estar vacio."
        else:  # date_diff
            if not self._combo_date_a.currentText():
                return "Selecciona la columna de Fecha A."
            if not self._combo_date_b.currentText():
                return "Selecciona la columna de Fecha B."
            if self._combo_date_a.currentText() == self._combo_date_b.currentText():
                return "Las columnas de fecha A y B deben ser distintas."
        return None


# ---------------------------------------------------------------------------
# Widget: un GroupBox completo para una regla
# ---------------------------------------------------------------------------

class RuleGroupBox(QWidget):
    """
    Encapsula una regla completa: nombre de columna destino, tipo y parametros.
    Emite move_up / move_down / remove_requested / rule_changed.
    """

    move_up = Signal(object)
    move_down = Signal(object)
    remove_requested = Signal(object)
    rule_changed = Signal(object)  # emite self

    def __init__(
        self,
        index: int,
        columns: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._index = index

        # Timer para debounce del preview (500 ms)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(500)
        self._preview_timer.timeout.connect(self._emit_rule_changed)

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(4)

        # GroupBox principal
        self._box = QGroupBox()
        self._box.setStyleSheet(
            f"QGroupBox {{ border: 1.5px solid #c0d0e0; border-radius: 6px; "
            f"margin-top: 6px; background: white; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; "
            f"color: {COLOR_PRIMARY}; font-weight: bold; }}"
        )
        box_lay = QVBoxLayout(self._box)
        box_lay.setContentsMargins(12, 10, 12, 10)
        box_lay.setSpacing(8)

        # --- Fila de cabecera ---
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        lbl_num = QLabel(f"Regla {self._index + 1}")
        lbl_num.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {COLOR_PRIMARY};"
        )
        header_row.addWidget(lbl_num)
        self._lbl_num = lbl_num

        header_row.addStretch()

        btn_up = QPushButton("▲")
        btn_up.setFixedSize(28, 26)
        btn_up.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1px solid #ccd6e0; "
            f"border-radius: 4px; font-size: 10px;"
        )
        btn_up.setToolTip("Subir esta regla")
        btn_up.clicked.connect(lambda: self.move_up.emit(self))
        header_row.addWidget(btn_up)

        btn_down = QPushButton("▼")
        btn_down.setFixedSize(28, 26)
        btn_down.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1px solid #ccd6e0; "
            f"border-radius: 4px; font-size: 10px;"
        )
        btn_down.setToolTip("Bajar esta regla")
        btn_down.clicked.connect(lambda: self.move_down.emit(self))
        header_row.addWidget(btn_down)

        btn_rm = QPushButton("✕")
        btn_rm.setFixedSize(28, 26)
        btn_rm.setStyleSheet(
            f"color: {COLOR_ERROR}; font-weight: bold; font-size: 13px; "
            f"border: 1.5px solid {COLOR_ERROR}; border-radius: 4px; background: white;"
        )
        btn_rm.setToolTip("Eliminar esta regla")
        btn_rm.clicked.connect(lambda: self.remove_requested.emit(self))
        header_row.addWidget(btn_rm)

        box_lay.addLayout(header_row)

        # --- Columna destino + tipo ---
        dest_row = QHBoxLayout()
        dest_row.setSpacing(12)

        lbl_dest = QLabel("Columna destino:")
        lbl_dest.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        lbl_dest.setMinimumWidth(120)
        dest_row.addWidget(lbl_dest)

        self._input_output_col = QLineEdit()
        self._input_output_col.setPlaceholderText("Ej: Atribucion")
        self._input_output_col.setMinimumWidth(160)
        self._input_output_col.setStyleSheet(
            f"border: 1.5px solid #ccd6e0; border-radius: 4px; "
            f"padding: 3px 8px; font-size: 12px; color: {COLOR_TEXT_DARK};"
        )
        self._input_output_col.textChanged.connect(self._on_field_changed)
        dest_row.addWidget(self._input_output_col)

        lbl_type = QLabel("Tipo:")
        lbl_type.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        dest_row.addWidget(lbl_type)

        self._combo_type = QComboBox()
        for key, label in _RULE_TYPE_LABELS.items():
            self._combo_type.addItem(label, key)
        self._combo_type.setMinimumWidth(200)
        self._combo_type.currentIndexChanged.connect(self._on_type_changed)
        dest_row.addWidget(self._combo_type)
        dest_row.addStretch()

        box_lay.addLayout(dest_row)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #d8e4f0;")
        box_lay.addWidget(sep)

        # --- Panel de parametros dinamicos ---
        self._params_widget = RuleParamsWidget(columns=self._columns)
        self._params_widget.params_changed.connect(self._on_field_changed)
        box_lay.addWidget(self._params_widget)

        # --- Separador antes del preview ---
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #d8e4f0;")
        box_lay.addWidget(sep2)

        # --- Preview ---
        lbl_preview_title = QLabel("Vista previa (5 filas):")
        lbl_preview_title.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {COLOR_TEXT_MID};"
        )
        box_lay.addWidget(lbl_preview_title)

        self._preview_table = QTableWidget(0, 2)
        self._preview_table.setHorizontalHeaderLabels(
            ["Columnas involucradas", "Resultado"]
        )
        self._preview_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._preview_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._preview_table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {COLOR_PRIMARY_LIGHT}; color: {COLOR_TEXT_DARK}; "
            f"  font-size: 11px; font-weight: bold; "
            f"  border: 1px solid #c8d8ea; padding: 3px 6px;"
            f"}}"
        )
        self._preview_table.verticalHeader().setVisible(False)
        self._preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._preview_table.setMaximumHeight(130)
        self._preview_table.setStyleSheet(
            f"QTableWidget {{ font-size: 11px; color: {COLOR_TEXT_DARK}; "
            f"gridline-color: #d8e4f0; }}"
        )
        box_lay.addWidget(self._preview_table)

        self._lbl_preview_error = QLabel("")
        self._lbl_preview_error.setWordWrap(True)
        self._lbl_preview_error.setStyleSheet(
            f"font-size: 11px; color: {_COLOR_PREVIEW_ERROR};"
        )
        self._lbl_preview_error.hide()
        box_lay.addWidget(self._lbl_preview_error)

        outer.addWidget(self._box)

    # ------------------------------------------------------------------ #
    # Slots internos                                                       #
    # ------------------------------------------------------------------ #

    def _on_type_changed(self, _idx: int) -> None:
        rule_type = self._combo_type.currentData()
        self._params_widget.set_rule_type(rule_type)
        self._on_field_changed()

    def _on_field_changed(self, *_) -> None:
        self._preview_timer.start()

    def _emit_rule_changed(self) -> None:
        self.rule_changed.emit(self)

    # ------------------------------------------------------------------ #
    # Actualizacion del numero de regla (cuando se reordenan)             #
    # ------------------------------------------------------------------ #

    def set_index(self, index: int) -> None:
        self._index = index
        self._lbl_num.setText(f"Regla {index + 1}")

    # ------------------------------------------------------------------ #
    # Lectura de la regla configurada                                      #
    # ------------------------------------------------------------------ #

    def get_rule(self) -> BusinessRule | None:
        """
        Retorna el BusinessRule configurado, o None si la columna destino esta vacia.
        """
        output_col = self._input_output_col.text().strip()
        if not output_col:
            return None
        rule_type = self._combo_type.currentData()
        params = self._params_widget.get_params()
        return BusinessRule.new(
            output_column=output_col,
            rule_type=rule_type,
            params=params,
        )

    def get_validation_error(self) -> str | None:
        """Retorna descripcion del error de configuracion, o None si OK."""
        if not self._input_output_col.text().strip():
            return "La columna destino no puede estar vacia."
        return self._params_widget.validate()

    # ------------------------------------------------------------------ #
    # Actualizacion del preview                                            #
    # ------------------------------------------------------------------ #

    def update_preview(self, df: pd.DataFrame) -> None:
        """
        Ejecuta el preview con el DataFrame recibido y actualiza la tabla.
        Se llama desde RulesScreen cuando rule_changed se emite.
        """
        self._lbl_preview_error.hide()
        self._preview_table.setRowCount(0)

        err = self.get_validation_error()
        if err:
            self._lbl_preview_error.setText(f"Configuracion incompleta: {err}")
            self._lbl_preview_error.show()
            return

        rule = self.get_rule()
        if rule is None:
            return

        rows = preview_rule(df, rule, n=5)
        if not rows:
            self._lbl_preview_error.setText(
                "No hay datos disponibles para la vista previa, "
                "o las columnas elegidas no son compatibles con esta regla."
            )
            self._lbl_preview_error.show()
            return

        self._preview_table.setRowCount(len(rows))
        for i, (resumen, valor) in enumerate(rows):
            item_resumen = QTableWidgetItem(resumen)
            item_resumen.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item_valor = QTableWidgetItem(valor)
            item_valor.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._preview_table.setItem(i, 0, item_resumen)
            self._preview_table.setItem(i, 1, item_valor)


# ---------------------------------------------------------------------------
# Pantalla principal
# ---------------------------------------------------------------------------

class RulesScreen(QWidget):
    """
    Pantalla de reglas de negocio (paso opcional entre cruce y resultado).

    Senales:
      rules_completed(CrossResult)  — result con columnas nuevas aplicadas
      skip_requested(CrossResult)   — result original sin modificar
      back_requested()              — volver a la pantalla de cruce
    """

    rules_completed = Signal(object)   # CrossResult con df modificado
    skip_requested = Signal(object)    # CrossResult original
    back_requested = Signal()

    def __init__(self, audit_logger: AuditLogger, parent=None) -> None:
        super().__init__(parent)
        self._logger = audit_logger
        self._result: CrossResult | None = None
        self._current_user: str = ""
        self._rule_groups: list[RuleGroupBox] = []

        self._build_ui()

    # ------------------------------------------------------------------
    # Construccion de UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 16, 24, 16)
        main_layout.setSpacing(10)

        # Titulo
        header = QLabel("Reglas de negocio (opcional)")
        header.setStyleSheet(STYLE_SCREEN_TITLE)
        main_layout.addWidget(header)

        desc = QLabel(
            "Crea columnas calculadas sobre el resultado del cruce. "
            "Podes saltear este paso si no necesitas transformaciones adicionales."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 12px;")
        main_layout.addWidget(desc)

        # --- Vista previa de datos (primeras 10 filas) ---
        preview_box = QGroupBox("Vista previa del resultado del cruce")
        preview_box.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: {COLOR_PRIMARY}; "
            f"border: 1.5px solid #c0d0e0; border-radius: 5px; margin-top: 8px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        preview_box_lay = QVBoxLayout(preview_box)

        self._data_preview = QTableWidget(0, 0)
        self._data_preview.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._data_preview.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {COLOR_PRIMARY}; color: white; "
            f"  font-weight: bold; font-size: 11px; "
            f"  border: 1px solid #1a5080; padding: 3px 6px;"
            f"}}"
        )
        self._data_preview.verticalHeader().setVisible(True)
        self._data_preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._data_preview.setMaximumHeight(180)
        self._data_preview.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._data_preview.setStyleSheet(
            f"QTableWidget {{ font-size: 11px; color: {COLOR_TEXT_DARK}; "
            f"gridline-color: #d8e4f0; }}"
        )
        preview_box_lay.addWidget(self._data_preview)
        main_layout.addWidget(preview_box)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #c8d8ea;")
        main_layout.addWidget(sep)

        # --- Panel de reglas (scroll vertical) ---
        lbl_rules = QLabel("Reglas definidas:")
        lbl_rules.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {COLOR_TEXT_DARK};"
        )
        main_layout.addWidget(lbl_rules)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: #f9fbfd;")

        self._rules_container = QWidget()
        self._rules_container.setStyleSheet("background-color: #f9fbfd;")
        self._rules_layout = QVBoxLayout(self._rules_container)
        self._rules_layout.setSpacing(6)
        self._rules_layout.setContentsMargins(4, 4, 4, 4)
        self._rules_layout.addStretch()

        scroll.setWidget(self._rules_container)
        main_layout.addWidget(scroll, 1)

        # Boton Agregar regla
        btn_add_row = QHBoxLayout()
        self._btn_add_rule = QPushButton("＋  Agregar regla")
        self._btn_add_rule.setMinimumHeight(34)
        self._btn_add_rule.setMaximumWidth(180)
        self._btn_add_rule.setStyleSheet(
            f"color: {COLOR_PRIMARY}; border: 1.5px solid {COLOR_PRIMARY}; "
            f"border-radius: 5px; font-size: 12px; font-weight: bold; "
            f"padding: 4px 14px; background: white;"
        )
        self._btn_add_rule.clicked.connect(self._on_add_rule)
        btn_add_row.addWidget(self._btn_add_rule)
        btn_add_row.addStretch()
        main_layout.addLayout(btn_add_row)

        # --- Botones de navegacion ---
        nav_row = QHBoxLayout()

        self._btn_back = QPushButton("← Volver al cruce")
        self._btn_back.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #ccd6e0; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        self._btn_back.clicked.connect(self.back_requested)
        nav_row.addWidget(self._btn_back)

        nav_row.addStretch()

        self._btn_skip = QPushButton("Saltear reglas  →")
        self._btn_skip.setMinimumHeight(38)
        self._btn_skip.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #ccd6e0; "
            f"border-radius: 4px; padding: 4px 18px; font-size: 12px;"
        )
        self._btn_skip.setToolTip(
            "Continuar al resultado sin aplicar reglas de negocio"
        )
        self._btn_skip.clicked.connect(self._on_skip)
        nav_row.addWidget(self._btn_skip)

        self._btn_apply = QPushButton("Aplicar reglas  →")
        self._btn_apply.setMinimumHeight(38)
        self._btn_apply.setStyleSheet(
            STYLE_BTN_PRIMARY + "font-size: 13px;"
        )
        self._btn_apply.setToolTip("Aplicar las reglas definidas y continuar al resultado")
        self._btn_apply.clicked.connect(self._on_apply)
        nav_row.addWidget(self._btn_apply)

        main_layout.addLayout(nav_row)

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------

    def load_result(self, result: CrossResult, current_user: str = "") -> None:
        """Carga el resultado del cruce para definir reglas sobre el."""
        self._result = result
        self._current_user = current_user

        # Limpiar reglas previas
        for group in list(self._rule_groups):
            self._rules_layout.removeWidget(group)
            group.deleteLater()
        self._rule_groups.clear()

        # Actualizar vista previa de datos
        self._refresh_data_preview()

    def _refresh_data_preview(self) -> None:
        """Muestra las primeras 10 filas del resultado en la tabla de preview."""
        self._data_preview.setRowCount(0)
        self._data_preview.setColumnCount(0)

        if self._result is None or self._result.df is None or self._result.df.empty:
            return

        df = self._result.df
        cols = list(df.columns)
        preview_df = df.head(10)

        self._data_preview.setColumnCount(len(cols))
        self._data_preview.setHorizontalHeaderLabels([str(c) for c in cols])
        self._data_preview.setRowCount(len(preview_df))

        for row_idx, (_, row) in enumerate(preview_df.iterrows()):
            for col_idx, col in enumerate(cols):
                val = row[col]
                try:
                    is_na = not isinstance(val, str) and pd.isna(val)
                except (TypeError, ValueError):
                    is_na = False
                text = "" if is_na else str(val)
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self._data_preview.setItem(row_idx, col_idx, item)

    def _get_result_columns(self) -> list[str]:
        if self._result is None or self._result.df is None:
            return []
        return list(self._result.df.columns)

    # ------------------------------------------------------------------
    # Gestion de reglas
    # ------------------------------------------------------------------

    def _on_add_rule(self) -> None:
        columns = self._get_result_columns()
        if not columns:
            QMessageBox.warning(
                self,
                "Sin datos",
                "No hay datos del cruce disponibles para definir reglas.",
            )
            return

        idx = len(self._rule_groups)
        group = RuleGroupBox(index=idx, columns=columns)
        group.move_up.connect(self._on_rule_move_up)
        group.move_down.connect(self._on_rule_move_down)
        group.remove_requested.connect(self._on_rule_remove)
        group.rule_changed.connect(self._on_rule_changed)

        self._rule_groups.append(group)
        # Insertar antes del stretch
        self._rules_layout.insertWidget(self._rules_layout.count() - 1, group)

    def _on_rule_remove(self, group: RuleGroupBox) -> None:
        self._rule_groups.remove(group)
        self._rules_layout.removeWidget(group)
        group.deleteLater()
        self._renumber_rules()

    def _on_rule_move_up(self, group: RuleGroupBox) -> None:
        idx = self._rule_groups.index(group)
        if idx == 0:
            return
        self._rule_groups[idx], self._rule_groups[idx - 1] = (
            self._rule_groups[idx - 1],
            self._rule_groups[idx],
        )
        self._rebuild_rules_layout()

    def _on_rule_move_down(self, group: RuleGroupBox) -> None:
        idx = self._rule_groups.index(group)
        if idx >= len(self._rule_groups) - 1:
            return
        self._rule_groups[idx], self._rule_groups[idx + 1] = (
            self._rule_groups[idx + 1],
            self._rule_groups[idx],
        )
        self._rebuild_rules_layout()

    def _rebuild_rules_layout(self) -> None:
        """Re-inserta los widgets en el layout segun el orden actual de _rule_groups."""
        for group in self._rule_groups:
            self._rules_layout.removeWidget(group)
        for i, group in enumerate(self._rule_groups):
            self._rules_layout.insertWidget(i, group)
        self._renumber_rules()

    def _renumber_rules(self) -> None:
        for i, group in enumerate(self._rule_groups):
            group.set_index(i)

    def _on_rule_changed(self, group: RuleGroupBox) -> None:
        """Actualiza el preview de la regla que cambio."""
        if self._result is None or self._result.df is None:
            return
        group.update_preview(self._result.df)

    # ------------------------------------------------------------------
    # Acciones de navegacion
    # ------------------------------------------------------------------

    def _on_skip(self) -> None:
        if self._result is None:
            return
        self.skip_requested.emit(self._result)

    def _on_apply(self) -> None:
        if self._result is None or self._result.df is None:
            self.skip_requested.emit(self._result)
            return

        rules = self._collect_valid_rules()

        if not rules:
            # Si no hay reglas configuradas, comportamiento equivalente a saltear
            self.skip_requested.emit(self._result)
            return

        # V6-SEG-02: detectar reglas que no pueden aplicarse antes de apply_all_rules.
        # Se intenta cada regla individualmente; las que lanzan excepcion se registran
        # en el log de auditoria como "reglas_saltadas".
        # TODO V6-SEG-02: cuando el motor exponga internamente la lista de reglas
        # saltadas (ej. via apply_all_rules con retorno extendido), reemplazar este
        # loop por esa interfaz para evitar la doble evaluacion.
        reglas_saltadas: list[dict] = []
        for r in rules:
            try:
                apply_rule(self._result.df, r)
            except Exception:
                reglas_saltadas.append(
                    {"rule_id": r.rule_id, "output_column": r.output_column}
                )

        # Aplicar reglas
        try:
            new_df = apply_all_rules(self._result.df, rules)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error al aplicar reglas",
                f"Ocurrio un problema inesperado al aplicar las reglas:\n{exc}\n\n"
                "Revisa la configuracion de las reglas e intenta de nuevo.",
            )
            return

        # Construir nuevo CrossResult con el df modificado
        new_result = dc_replace(
            self._result,
            df=new_df,
            row_count=len(new_df),
        )

        # Audit log — RN-019: solo nombres de columna, sin literales de valores
        output_columns = [r.output_column for r in rules]
        rule_types = [r.rule_type for r in rules]
        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._current_user,
            accion="RULES_APPLY",
            columnas=output_columns,
            filas_procesadas=len(new_df),
            extra={
                "rule_types": rule_types,
                "rules_count": len(rules),
                "reglas_saltadas": reglas_saltadas,
            },
        ))

        self.rules_completed.emit(new_result)

    def _collect_valid_rules(self) -> list[BusinessRule]:
        """Retorna las reglas bien configuradas (columna destino + params validos)."""
        rules: list[BusinessRule] = []
        for group in self._rule_groups:
            err = group.get_validation_error()
            if err:
                continue
            rule = group.get_rule()
            if rule is not None:
                rules.append(rule)
        return rules
