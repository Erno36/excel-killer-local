"""
ui/cross_screen.py — Pantalla de configuracion del cruce.

HU-04: seleccion de columnas clave, tipo de join, normalizacion, ejecucion.
Soporta claves compuestas: cada paso de cruce puede tener N pares de columnas.
El usuario configura los vinculos mediante una interfaz visual de tres paneles
(columnas LEFT | vinculos activos | columnas RIGHT) con auto-deteccion de pares.
"""
from __future__ import annotations

from dataclasses import replace as dc_replace

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from audit.logger import AuditLogger, make_timestamp
from data.models import AuditEntry, CleansingRule, CrossConfig, CrossResult, FileEntry, Recipe
from engine.column_matcher import TYPE_ICON, infer_column_type, suggest_pairs
from engine.cross import CrossConfigError, execute_cross
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
# Worker thread para el cruce (no bloquea la UI)
# ---------------------------------------------------------------------------

class CrossWorker(QObject):
    finished = Signal(object)   # CrossResult
    error = Signal(str)         # mensaje de error para el usuario

    def __init__(self, config: CrossConfig) -> None:
        super().__init__()
        self._config = config

    def run(self) -> None:
        try:
            result = execute_cross(self._config)
            self.finished.emit(result)
        except CrossConfigError as exc:
            self.error.emit(str(exc))
        except Exception:
            self.error.emit(
                "Ocurrio un problema inesperado al procesar el cruce.\n"
                "Si el problema persiste, comunicate con el equipo de Sistemas."
            )


# ---------------------------------------------------------------------------
# Widget: seccion visual de un paso de cruce (tres paneles)
# ---------------------------------------------------------------------------

class VisualCrossSection(QWidget):
    """
    Interfaz visual de mapeo de columnas para un paso del cruce.

    Layout de tres paneles:
        Columnas LEFT | Vinculos activos | Columnas RIGHT

    - Las listas muestran el icono de tipo semantico inferido.
    - El usuario selecciona una columna de cada lado y presiona "Vincular".
    - "Auto-detectar" sugiere pares por similitud de nombre.
    - Cada vinculo activo tiene un boton x para eliminarlo.
    - Se muestra advertencia cuando los tipos de ambas columnas difieren.
    """

    def __init__(
        self,
        step_index: int,
        left_entry: FileEntry,
        right_entry: FileEntry,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._step_index = step_index
        self.__left = left_entry
        self.__right = right_entry

        # Cache de tipos inferidos: {col_name: tipo}
        self._left_types: dict[str, str] = {}
        self._right_types: dict[str, str] = {}

        # Lista interna de pares activos
        self._pairs: list[tuple[str, str]] = []

        self._build_ui()
        self._populate_column_lists()

    # ------------------------------------------------------------------
    # Propiedades publicas para compatibilidad con CrossScreen
    # ------------------------------------------------------------------

    @property
    def _left(self) -> FileEntry:
        return self.__left

    @property
    def _right(self) -> FileEntry:
        return self.__right

    # ------------------------------------------------------------------
    # Construccion de la UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 6)
        outer.setSpacing(6)

        # --- Encabezado del paso ---
        header_frame = QFrame()
        header_frame.setStyleSheet(
            f"background-color: {COLOR_PRIMARY_LIGHT}; "
            f"border-left: 4px solid {COLOR_PRIMARY}; "
            f"border-radius: 0px 4px 4px 0px; padding: 2px;"
        )
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 6, 10, 6)

        step_lbl = QLabel(
            f"Paso {self._step_index + 1}:  "
            f"<b>{self.__left.label}</b>  ↔  <b>{self.__right.label}</b>"
        )
        step_lbl.setStyleSheet(
            f"font-size: 12px; color: {COLOR_PRIMARY}; background: transparent;"
        )
        header_layout.addWidget(step_lbl)
        header_layout.addStretch()
        outer.addWidget(header_frame)

        # --- Splitter de tres paneles ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Panel izquierdo: columnas LEFT
        left_panel = QWidget()
        left_panel.setMinimumWidth(160)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)

        lbl_left_title = QLabel(f"Columnas de <b>{self.__left.label}</b>")
        lbl_left_title.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        lbl_left_title.setWordWrap(True)
        left_layout.addWidget(lbl_left_title)

        self._list_left = QListWidget()
        self._list_left.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list_left.setStyleSheet(
            "QListWidget { border: 1.5px solid #ccd6e0; border-radius: 4px; "
            "background: white; font-size: 11px; }"
            "QListWidget::item:selected { background-color: #d0e8f8; color: #003366; }"
        )
        self._list_left.itemSelectionChanged.connect(self._update_link_button)
        left_layout.addWidget(self._list_left)

        splitter.addWidget(left_panel)

        # Panel central: vinculos activos + botones
        center_panel = QWidget()
        center_panel.setMinimumWidth(220)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(6, 4, 6, 4)
        center_layout.setSpacing(6)

        lbl_center_title = QLabel("Vinculos activos")
        lbl_center_title.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {COLOR_PRIMARY};"
        )
        lbl_center_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(lbl_center_title)

        # Contenedor de pares
        self._pairs_container = QWidget()
        self._pairs_layout = QVBoxLayout(self._pairs_container)
        self._pairs_layout.setContentsMargins(0, 0, 0, 0)
        self._pairs_layout.setSpacing(3)
        self._pairs_layout.addStretch()
        center_layout.addWidget(self._pairs_container, 1)

        # Boton vincular
        self._btn_link = QPushButton("↔ Vincular seleccionados")
        self._btn_link.setEnabled(False)
        self._btn_link.setStyleSheet(
            f"color: white; background-color: {COLOR_PRIMARY}; "
            f"border: none; border-radius: 4px; font-size: 11px; "
            f"font-weight: bold; padding: 5px 10px;"
        )
        self._btn_link.setToolTip(
            "Crear un vinculo entre la columna seleccionada en cada lista"
        )
        self._btn_link.clicked.connect(self._on_link)
        center_layout.addWidget(self._btn_link)

        # Boton auto-detectar
        self._btn_auto = QPushButton("★ Auto-detectar")
        self._btn_auto.setStyleSheet(
            f"color: {COLOR_PRIMARY}; border: 1.5px solid {COLOR_PRIMARY}; "
            f"border-radius: 4px; font-size: 11px; padding: 4px 10px;"
        )
        self._btn_auto.setToolTip(
            "Detectar automaticamente pares de columnas por similitud de nombre"
        )
        self._btn_auto.clicked.connect(self._on_auto_detect)
        center_layout.addWidget(self._btn_auto)

        splitter.addWidget(center_panel)

        # Panel derecho: columnas RIGHT
        right_panel = QWidget()
        right_panel.setMinimumWidth(160)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)

        lbl_right_title = QLabel(f"Columnas de <b>{self.__right.label}</b>")
        lbl_right_title.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        lbl_right_title.setWordWrap(True)
        right_layout.addWidget(lbl_right_title)

        self._list_right = QListWidget()
        self._list_right.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list_right.setStyleSheet(
            "QListWidget { border: 1.5px solid #ccd6e0; border-radius: 4px; "
            "background: white; font-size: 11px; }"
            "QListWidget::item:selected { background-color: #d0e8f8; color: #003366; }"
        )
        self._list_right.itemSelectionChanged.connect(self._update_link_button)
        right_layout.addWidget(self._list_right)

        splitter.addWidget(right_panel)

        # Tamaños iniciales del splitter: 35% / 30% / 35%
        splitter.setSizes([350, 300, 350])
        outer.addWidget(splitter)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #d0dce8;")
        outer.addWidget(sep)

    # ------------------------------------------------------------------
    # Poblado de listas
    # ------------------------------------------------------------------

    def _icon_label(self, col: str, tipo: str) -> str:
        icon = TYPE_ICON.get(tipo, "")
        return f"{icon} {col}" if icon else col

    def _populate_column_lists(self) -> None:
        self._list_left.clear()
        self._list_right.clear()
        self._left_types.clear()
        self._right_types.clear()

        for col in self.__left.metadata.column_names:
            tipo = infer_column_type(self.__left.df[col])
            self._left_types[col] = tipo
            item = QListWidgetItem(self._icon_label(col, tipo))
            item.setData(Qt.ItemDataRole.UserRole, col)
            self._list_left.addItem(item)

        for col in self.__right.metadata.column_names:
            tipo = infer_column_type(self.__right.df[col])
            self._right_types[col] = tipo
            item = QListWidgetItem(self._icon_label(col, tipo))
            item.setData(Qt.ItemDataRole.UserRole, col)
            self._list_right.addItem(item)

    # ------------------------------------------------------------------
    # Logica de vinculos
    # ------------------------------------------------------------------

    def _update_link_button(self) -> None:
        left_sel = self._list_left.selectedItems()
        right_sel = self._list_right.selectedItems()
        self._btn_link.setEnabled(bool(left_sel and right_sel))

    def _on_link(self) -> None:
        left_items = self._list_left.selectedItems()
        right_items = self._list_right.selectedItems()
        if not left_items or not right_items:
            return

        col_left  = left_items[0].data(Qt.ItemDataRole.UserRole)
        col_right = right_items[0].data(Qt.ItemDataRole.UserRole)

        if (col_left, col_right) in self._pairs:
            QMessageBox.warning(
                self,
                "Vinculo duplicado",
                f"El vinculo '{col_left}' ↔ '{col_right}' ya existe.",
            )
            return

        self._add_pair_internal(col_left, col_right)
        # Deseleccionar ambas listas
        self._list_left.clearSelection()
        self._list_right.clearSelection()

    def _on_auto_detect(self) -> None:
        left_cols  = self.__left.metadata.column_names
        right_cols = self.__right.metadata.column_names
        suggestions = suggest_pairs(left_cols, right_cols)

        if not suggestions:
            QMessageBox.information(
                self,
                "Sin coincidencias",
                "No se encontraron coincidencias automaticas. "
                "Configura los vinculos manualmente.",
            )
            return

        # Reemplazar pares actuales
        self._clear_all_pairs()
        for col_left, col_right in suggestions:
            self._add_pair_internal(col_left, col_right)

    def _clear_all_pairs(self) -> None:
        """Elimina todos los vinculos activos sin confirmacion (uso interno)."""
        self._pairs.clear()
        # Vaciar el layout de pares (preservar el stretch al final)
        while self._pairs_layout.count() > 1:
            item = self._pairs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_pair_internal(self, col_left: str, col_right: str) -> None:
        """Agrega un par a la lista interna y crea su widget en el panel central."""
        self._pairs.append((col_left, col_right))

        pair_widget = QWidget()
        pair_layout = QHBoxLayout(pair_widget)
        pair_layout.setContentsMargins(4, 2, 4, 2)
        pair_layout.setSpacing(4)

        tipo_left  = self._left_types.get(col_left, "texto")
        tipo_right = self._right_types.get(col_right, "texto")

        icon_left  = TYPE_ICON.get(tipo_left, "")
        icon_right = TYPE_ICON.get(tipo_right, "")

        lbl_pair = QLabel(
            f"{icon_left} {col_left}  ↔  {icon_right} {col_right}"
        )
        lbl_pair.setStyleSheet(
            f"font-size: 11px; color: {COLOR_TEXT_DARK}; "
            f"background: #f0f6fc; border-radius: 3px; padding: 2px 4px;"
        )
        lbl_pair.setWordWrap(True)
        pair_layout.addWidget(lbl_pair, 1)

        # Advertencia de tipos distintos
        if tipo_left != tipo_right:
            lbl_warn = QLabel("⚠️")
            lbl_warn.setToolTip(
                "Tipos distintos: el cruce puede tener resultados inesperados."
            )
            lbl_warn.setStyleSheet("font-size: 13px;")
            pair_layout.addWidget(lbl_warn)

        # Boton eliminar
        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(26)
        btn_remove.setFixedHeight(24)
        btn_remove.setStyleSheet(
            f"color: {COLOR_ERROR}; font-weight: bold; font-size: 12px; "
            f"border: 1.5px solid {COLOR_ERROR}; border-radius: 3px; background: white;"
        )
        btn_remove.setToolTip("Eliminar este vinculo")

        # Captura por closure: index relativo al momento de creacion
        pair_ref = (col_left, col_right)
        btn_remove.clicked.connect(lambda _=False, p=pair_ref, w=pair_widget: self._remove_pair(p, w))
        pair_layout.addWidget(btn_remove)

        # Insertar antes del stretch (ultimo elemento del layout)
        insert_pos = max(0, self._pairs_layout.count() - 1)
        self._pairs_layout.insertWidget(insert_pos, pair_widget)

    def _remove_pair(self, pair: tuple[str, str], widget: QWidget) -> None:
        if len(self._pairs) <= 1:
            QMessageBox.information(
                self,
                "Minimo requerido",
                "Cada paso del cruce debe tener al menos un vinculo de columnas.",
            )
            return
        if pair in self._pairs:
            self._pairs.remove(pair)
        self._pairs_layout.removeWidget(widget)
        widget.deleteLater()

    # ------------------------------------------------------------------
    # Interfaz publica
    # ------------------------------------------------------------------

    def get_pairs(self) -> list[tuple[str, str]]:
        """Retorna la lista de pares (col_izq, col_der) activos."""
        return list(self._pairs)

    def set_pairs(self, pairs: list[tuple[str, str]]) -> None:
        """
        Reemplaza los pares activos con la lista dada.
        Ignora silenciosamente los pares cuyas columnas no existen en los archivos.
        """
        left_cols  = set(self.__left.metadata.column_names)
        right_cols = set(self.__right.metadata.column_names)

        valid_pairs = [
            (l, r) for l, r in pairs
            if l in left_cols and r in right_cols
        ]

        self._clear_all_pairs()
        for col_left, col_right in valid_pairs:
            self._add_pair_internal(col_left, col_right)


# ---------------------------------------------------------------------------
# Pantalla principal
# ---------------------------------------------------------------------------

class CrossScreen(QWidget):
    """
    Pantalla de configuracion del cruce.
    Emite cross_completed(CrossResult) cuando el cruce finaliza.
    Emite back_requested() para volver a la pantalla de carga.
    """

    cross_completed = Signal(object)   # CrossResult
    back_requested = Signal()
    # (file_entries, cleansing_rules, cross_steps, join_type, normalize_keys)
    save_recipe_requested = Signal(list, list, list, str, bool)

    def __init__(self, audit_logger: AuditLogger, parent=None) -> None:
        super().__init__(parent)
        self._logger = audit_logger
        self._file_entries: list[FileEntry] = []
        self._cleansing_rules: list[CleansingRule] = []
        self._pair_sections: list[VisualCrossSection] = []
        self._thread: QThread | None = None
        self._current_user: str = ""

        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 16, 24, 16)
        main_layout.setSpacing(12)

        # --- Titulo ---
        header = QLabel("Configuracion del cruce")
        header.setStyleSheet(STYLE_SCREEN_TITLE)
        main_layout.addWidget(header)

        desc = QLabel(
            "Selecciona una columna de cada lista y presiona '↔ Vincular seleccionados' "
            "para definir las columnas clave. Usa 'Auto-detectar' para sugerencias automaticas."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 12px;")
        main_layout.addWidget(desc)

        # --- Nombre del cruce ---
        name_row = QHBoxLayout()
        lbl_name = QLabel("Nombre del cruce:")
        lbl_name.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-weight: bold; font-size: 12px;")
        lbl_name.setMinimumWidth(130)
        name_row.addWidget(lbl_name)

        self._input_name = QLineEdit()
        self._input_name.setPlaceholderText("Ej: Seguros vs Bajas — Octubre 2026")
        self._input_name.setMinimumWidth(380)
        self._input_name.setStyleSheet(
            f"border: 1.5px solid #ccd6e0; border-radius: 4px; "
            f"padding: 4px 10px; color: {COLOR_TEXT_DARK}; font-size: 12px;"
        )
        name_row.addWidget(self._input_name)
        name_row.addStretch()
        main_layout.addLayout(name_row)

        # --- Area scroll para las secciones de pares ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: #f9fbfd;")

        self._sections_container = QWidget()
        self._sections_container.setStyleSheet("background-color: #f9fbfd;")
        self._sections_layout = QVBoxLayout(self._sections_container)
        self._sections_layout.setSpacing(4)
        self._sections_layout.setContentsMargins(4, 4, 4, 4)
        self._sections_layout.addStretch()

        scroll.setWidget(self._sections_container)
        main_layout.addWidget(scroll, 1)

        # --- Opciones de cruce ---
        opts_group = QGroupBox("Opciones del cruce")
        opts_group.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: {COLOR_PRIMARY}; "
            f"border: 1.5px solid #c0d0e0; border-radius: 5px; margin-top: 8px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        opts_layout = QVBoxLayout(opts_group)

        join_row = QHBoxLayout()
        lbl_join = QLabel("Tipo de cruce:")
        lbl_join.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-weight: bold; font-size: 12px;")
        join_row.addWidget(lbl_join)

        self._combo_join = QComboBox()
        self._combo_join.addItems([
            "outer  —  Todas las filas de todos los archivos",
            "inner  —  Solo filas con coincidencia en todos",
            "left   —  Todas las filas del primer archivo",
        ])
        self._combo_join.setCurrentIndex(0)
        self._combo_join.setMinimumWidth(340)
        join_row.addWidget(self._combo_join)
        join_row.addStretch()
        opts_layout.addLayout(join_row)

        self._chk_normalize = QCheckBox(
            "Normalizar claves antes de cruzar "
            "(elimina espacios al inicio/fin y unifica mayusculas/minusculas)"
        )
        self._chk_normalize.setChecked(True)
        self._chk_normalize.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 12px;")
        opts_layout.addWidget(self._chk_normalize)

        main_layout.addWidget(opts_group)

        # --- Barra de progreso (oculta) ---
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.hide()
        main_layout.addWidget(self._progress)

        # --- Advertencias ---
        self._warnings_label = QLabel("")
        self._warnings_label.setWordWrap(True)
        self._warnings_label.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 11px; "
            f"background-color: #fff7ee; border-radius: 4px; padding: 6px;"
        )
        self._warnings_label.hide()
        main_layout.addWidget(self._warnings_label)

        # --- Botones ---
        btn_row = QHBoxLayout()

        self._btn_back = QPushButton("← Volver a carga de archivos")
        self._btn_back.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #ccd6e0; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        self._btn_back.clicked.connect(self.back_requested)
        btn_row.addWidget(self._btn_back)

        btn_row.addStretch()

        self._btn_dryrun = QPushButton("Vista previa (verificar sin ejecutar)")
        self._btn_dryrun.setStyleSheet(
            f"color: {COLOR_PRIMARY}; border: 1.5px solid {COLOR_PRIMARY}; "
            f"border-radius: 4px; padding: 4px 14px; font-weight: bold;"
        )
        self._btn_dryrun.clicked.connect(self._on_dry_run)
        btn_row.addWidget(self._btn_dryrun)

        _COLOR_RECIPE = "#e67e22"
        self._btn_save_recipe = QPushButton("Guardar receta")
        self._btn_save_recipe.setStyleSheet(
            f"color: {_COLOR_RECIPE}; border: 1.5px solid {_COLOR_RECIPE}; "
            f"border-radius: 4px; font-weight: bold; padding: 4px 14px;"
        )
        self._btn_save_recipe.setToolTip(
            "Guardar este flujo (limpieza + cruce) como receta reutilizable."
        )
        self._btn_save_recipe.clicked.connect(self._on_save_recipe)
        btn_row.addWidget(self._btn_save_recipe)

        self._btn_execute = QPushButton("Ejecutar cruce  →")
        self._btn_execute.setMinimumHeight(42)
        self._btn_execute.setStyleSheet(STYLE_BTN_PRIMARY + "font-size: 13px;")
        self._btn_execute.clicked.connect(self._on_execute)
        btn_row.addWidget(self._btn_execute)

        main_layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Carga de archivos
    # ------------------------------------------------------------------

    def load_files(self, file_entries: list[FileEntry], current_user: str = "") -> None:
        """Configura la pantalla con los archivos cargados."""
        self._file_entries = file_entries
        self._current_user = current_user
        self._input_name.clear()
        self._warnings_label.hide()

        # Limpiar secciones anteriores.
        for section in self._pair_sections:
            self._sections_layout.removeWidget(section)
            section.deleteLater()
        self._pair_sections.clear()

        # Crear una seccion por cada par de archivos adyacentes.
        for i in range(len(file_entries) - 1):
            section = VisualCrossSection(
                step_index=i,
                left_entry=file_entries[i],
                right_entry=file_entries[i + 1],
            )
            self._pair_sections.append(section)
            self._sections_layout.insertWidget(
                self._sections_layout.count() - 1, section
            )

    # ------------------------------------------------------------------
    # Construccion de la configuracion
    # ------------------------------------------------------------------

    def _get_join_type(self) -> str:
        return ["outer", "inner", "left"][self._combo_join.currentIndex()]

    def _build_config(self) -> CrossConfig:
        # Validar que todas las secciones tienen al menos un par.
        for section in self._pair_sections:
            if not section.get_pairs():
                QMessageBox.warning(
                    self,
                    "Faltan vinculos",
                    "Cada paso del cruce debe tener al menos un vinculo de columnas.",
                )
                raise CrossConfigError(
                    "Hay pasos del cruce sin columnas vinculadas."
                )

        steps_key_pairs = [s.get_pairs() for s in self._pair_sections]
        return CrossConfig(
            file_entries=self._file_entries,
            key_pairs=[pairs[0] for pairs in steps_key_pairs],  # compat backward
            join_type=self._get_join_type(),
            normalize_keys=self._chk_normalize.isChecked(),
            steps_key_pairs=steps_key_pairs,
        )

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------

    def _on_dry_run(self) -> None:
        try:
            config = self._build_config()
            result = execute_cross(config, dry_run=True)
            msg = (
                f"Configuracion valida.\n\n"
                f"Archivos a cruzar: {len(config.file_entries)}\n"
                f"Tipo de cruce: {config.join_type}\n"
                f"Filas estimadas (maximo entre los archivos): {result.row_count}\n"
                f"Columnas clave: {', '.join(result.columns_used)}"
            )
            if result.warnings:
                msg += "\n\nAdvertencias:\n" + "\n".join(f"• {w}" for w in result.warnings)
            QMessageBox.information(self, "Vista previa del cruce", msg)
        except CrossConfigError as exc:
            QMessageBox.warning(self, "Configuracion invalida", str(exc))
        except Exception:
            QMessageBox.critical(
                self,
                "Error",
                "Ocurrio un problema inesperado. Revisa la configuracion e intenta de nuevo.",
            )

    def _on_execute(self) -> None:
        try:
            config = self._build_config()
        except Exception as exc:
            QMessageBox.warning(self, "Configuracion invalida", str(exc))
            return

        # Advertencias de tipos antes de ejecutar.
        try:
            dry = execute_cross(config, dry_run=True)
            if dry.warnings:
                reply = QMessageBox.question(
                    self,
                    "Atencion antes de cruzar",
                    "Se encontraron las siguientes advertencias:\n\n"
                    + "\n".join(f"• {w}" for w in dry.warnings)
                    + "\n\n¿Queres continuar igual?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
        except CrossConfigError as exc:
            QMessageBox.warning(self, "Configuracion invalida", str(exc))
            return

        self._set_executing(True)

        self._thread = QThread()
        self._worker = CrossWorker(config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_cross_done)
        self._worker.error.connect(self._on_cross_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_cross_done(self, result: CrossResult) -> None:
        self._set_executing(False)

        cross_name = self._input_name.text().strip() or "Cruce sin nombre"
        named_result = dc_replace(result, name=cross_name)

        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._current_user,
            accion="CROSS_EXECUTE",
            archivos=[
                {"nombre": e.path.name if e.path else "[resultado_previo]", "etiqueta": e.label}
                for e in self._file_entries
            ],
            columnas=named_result.columns_used,
            filas_procesadas=named_result.row_count,
            tipo_join=named_result.join_type,
            duracion_ms=named_result.duration_ms,
            extra={"nombre_cruce": cross_name},
        ))

        if named_result.warnings:
            self._warnings_label.setText(
                "Advertencias del cruce:\n" + "\n".join(f"• {w}" for w in named_result.warnings)
            )
            self._warnings_label.show()
        else:
            self._warnings_label.hide()

        # Aviso explicito si el resultado es vacio.
        if named_result.row_count == 0:
            QMessageBox.warning(
                self,
                "Sin resultados en el cruce",
                "El cruce no encontro filas que coincidan con la configuracion elegida.\n\n"
                "Posibles causas:\n"
                "• Los valores de las columnas clave no coinciden entre los archivos.\n"
                "• El tipo de cruce es 'inner' y no hay coincidencias exactas.\n"
                "• La normalizacion esta desactivada y hay diferencias de mayusculas "
                "o espacios.\n\n"
                "Podes ajustar la configuracion y volver a ejecutar.",
            )

        self.cross_completed.emit(named_result)

    def _on_cross_error(self, message: str) -> None:
        self._set_executing(False)
        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._current_user,
            accion="ERROR",
            archivos=[
                {"nombre": e.path.name if e.path else "[resultado_previo]", "etiqueta": e.label}
                for e in self._file_entries
            ],
            mensaje_error=message,
        ))
        QMessageBox.critical(
            self,
            "No se pudo completar el cruce",
            f"{message}\n\n"
            "Si el problema persiste, comunicate con el equipo de Sistemas.",
        )

    def _set_executing(self, executing: bool) -> None:
        self._btn_execute.setEnabled(not executing)
        self._btn_dryrun.setEnabled(not executing)
        self._btn_back.setEnabled(not executing)
        self._btn_save_recipe.setEnabled(not executing)
        if executing:
            self._progress.show()
        else:
            self._progress.hide()

    # ------------------------------------------------------------------
    # Metodos para recetas
    # ------------------------------------------------------------------

    def set_cleansing_rules(self, rules: list[CleansingRule]) -> None:
        """Almacena las reglas de limpieza aplicadas para incluirlas en la receta."""
        self._cleansing_rules = list(rules)

    def load_recipe_config(
        self,
        recipe: Recipe,
        file_entries: list[FileEntry],
    ) -> None:
        """
        Pre-carga join_type, normalize_keys y pares de columnas desde la receta.
        Se llama despues de load_files() para que las secciones ya esten creadas.
        """
        # Tipo de join.
        join_map = {"outer": 0, "inner": 1, "left": 2}
        join_idx = join_map.get(recipe.join_type, 0)
        self._combo_join.setCurrentIndex(join_idx)

        # Normalizacion.
        self._chk_normalize.setChecked(recipe.normalize_keys)

        # Pares de columnas por paso.
        warnings: list[str] = []

        for step_idx, step in enumerate(recipe.cross_steps):
            if step_idx >= len(self._pair_sections):
                break
            section = self._pair_sections[step_idx]

            # Verificar que el paso corresponde al par correcto.
            if (section._left.label != step.left_label
                    or section._right.label != step.right_label):
                warnings.append(
                    f"El paso {step_idx + 1} de la receta espera "
                    f"'{step.left_label}' ↔ '{step.right_label}', "
                    f"pero los archivos son '{section._left.label}' ↔ '{section._right.label}'."
                )
                continue

            # Detectar columnas que no existen (para el aviso)
            left_cols  = set(section._left.metadata.column_names)
            right_cols = set(section._right.metadata.column_names)
            for col_left, col_right in step.key_pairs:
                if col_left not in left_cols:
                    warnings.append(
                        f"Paso {step_idx + 1}: columna '{col_left}' no encontrada "
                        f"en '{step.left_label}'. Se ignora ese vinculo."
                    )
                if col_right not in right_cols:
                    warnings.append(
                        f"Paso {step_idx + 1}: columna '{col_right}' no encontrada "
                        f"en '{step.right_label}'. Se ignora ese vinculo."
                    )

            # set_pairs ignora silenciosamente los pares invalidos
            section.set_pairs(step.key_pairs)

        if warnings:
            QMessageBox.warning(
                self,
                "Advertencias al cargar receta",
                "Se encontraron diferencias entre la receta y los archivos cargados:\n\n"
                + "\n".join(f"• {w}" for w in warnings)
                + "\n\nRevisa la configuracion antes de ejecutar el cruce.",
            )

    def _on_save_recipe(self) -> None:
        """Emite la senal con el estado actual para que main_window abra SaveRecipeDialog."""
        from data.models import CrossStepSpec
        cross_steps = [
            CrossStepSpec(
                left_label=section._left.label,
                right_label=section._right.label,
                key_pairs=section.get_pairs(),
            )
            for section in self._pair_sections
        ]
        self.save_recipe_requested.emit(
            list(self._file_entries),
            list(self._cleansing_rules),
            cross_steps,
            self._get_join_type(),
            self._chk_normalize.isChecked(),
        )
