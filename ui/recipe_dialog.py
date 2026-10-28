"""
ui/recipe_dialog.py — Dialogos modales para guardar y cargar recetas.

SaveRecipeDialog: abre desde CrossScreen; guarda el flujo completo.
LoadRecipeDialog: abre desde LoadScreen; mapea archivos nuevos a una receta.

RN-019: ningun valor de celda, path de usuario ni dato personal se registra
        en los logs de auditoria emitidos desde este modulo.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from audit.logger import AuditLogger, make_timestamp
from data.models import AuditEntry, CleansingRule, CrossStepSpec, FileEntry, Recipe
from engine.reader import ExcelFileReader, FileReadError, EmptyFileError
from engine.recipe import (
    build_recipe_from_state,
    delete_recipe,
    list_recipes,
    load_recipe,
    save_recipe,
    validate_recipe_against_entries,
)
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

# Estilo del boton con acento naranja (acciones secundarias de recetas).
_COLOR_RECIPE = "#e67e22"
_STYLE_BTN_RECIPE = (
    f"color: {_COLOR_RECIPE}; border: 1.5px solid {_COLOR_RECIPE}; "
    f"border-radius: 4px; font-weight: bold; padding: 4px 14px;"
)


# ---------------------------------------------------------------------------
# SaveRecipeDialog
# ---------------------------------------------------------------------------

class SaveRecipeDialog(QDialog):
    """
    Dialogo modal para guardar la configuracion actual como receta.
    Se abre desde CrossScreen.
    """

    def __init__(
        self,
        file_entries: list[FileEntry],
        cleansing_rules: list[CleansingRule],
        cross_steps: list[CrossStepSpec],
        join_type: str,
        normalize_keys: bool,
        recipes_dir: Path,
        audit_logger: AuditLogger,
        current_user: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._file_entries = file_entries
        self._cleansing_rules = cleansing_rules
        self._cross_steps = cross_steps
        self._join_type = join_type
        self._normalize_keys = normalize_keys
        self._recipes_dir = recipes_dir
        self._logger = audit_logger
        self._current_user = current_user

        self.setWindowTitle("Guardar receta")
        self.setMinimumWidth(500)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Titulo
        title = QLabel("Guardar receta")
        title.setStyleSheet(STYLE_SCREEN_TITLE)
        layout.addWidget(title)

        # Nombre (obligatorio)
        lbl_name = QLabel("Nombre de la receta *")
        lbl_name.setStyleSheet(
            f"font-weight: bold; color: {COLOR_PRIMARY}; font-size: 12px;"
        )
        layout.addWidget(lbl_name)

        self._input_name = QLineEdit()
        self._input_name.setPlaceholderText("Ej: Stock vs Bajas — proceso mensual")
        self._input_name.setStyleSheet(
            f"border: 1.5px solid #ccd6e0; border-radius: 4px; "
            f"padding: 4px 10px; color: {COLOR_TEXT_DARK}; font-size: 12px;"
        )
        layout.addWidget(self._input_name)

        # Descripcion (opcional)
        lbl_desc = QLabel("Descripcion (opcional)")
        lbl_desc.setStyleSheet(
            f"font-weight: bold; color: {COLOR_PRIMARY}; font-size: 12px;"
        )
        layout.addWidget(lbl_desc)

        self._input_desc = QLineEdit()
        self._input_desc.setPlaceholderText("Breve descripcion del proposito de esta receta")
        self._input_desc.setStyleSheet(
            f"border: 1.5px solid #ccd6e0; border-radius: 4px; "
            f"padding: 4px 10px; color: {COLOR_TEXT_DARK}; font-size: 12px;"
        )
        layout.addWidget(self._input_desc)

        # Resumen de lo que se guarda
        summary_frame = QFrame()
        summary_frame.setStyleSheet(
            f"background-color: {COLOR_PRIMARY_LIGHT}; border-radius: 6px; padding: 2px;"
        )
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(4)

        # Archivos incluidos
        file_labels = ", ".join(e.label for e in self._file_entries) or "(ninguno)"
        lbl_files = QLabel(f"Archivos incluidos: {file_labels}")
        lbl_files.setWordWrap(True)
        lbl_files.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        summary_layout.addWidget(lbl_files)

        # Reglas de limpieza
        n_rules = len(self._cleansing_rules)
        lbl_rules = QLabel(
            f"Reglas de limpieza: {n_rules} regla{'s' if n_rules != 1 else ''}"
        )
        lbl_rules.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        summary_layout.addWidget(lbl_rules)

        # Pasos de cruce
        n_steps = len(self._cross_steps)
        steps_desc = "; ".join(
            f"{s.left_label} ↔ {s.right_label}" for s in self._cross_steps
        ) or "(ninguno)"
        lbl_steps = QLabel(
            f"Pasos de cruce ({n_steps}): {steps_desc}"
        )
        lbl_steps.setWordWrap(True)
        lbl_steps.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        summary_layout.addWidget(lbl_steps)

        # Tipo de join
        lbl_join = QLabel(f"Tipo de cruce: {self._join_type}")
        lbl_join.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_DARK};")
        summary_layout.addWidget(lbl_join)

        layout.addWidget(summary_frame)

        # Botones
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #ccd6e0; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addStretch()

        btn_save = QPushButton("Guardar")
        btn_save.setMinimumHeight(38)
        btn_save.setStyleSheet(STYLE_BTN_PRIMARY + "font-size: 12px;")
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def _on_save(self) -> None:
        name = self._input_name.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                "Nombre requerido",
                "El nombre de la receta no puede estar vacio.",
            )
            self._input_name.setFocus()
            return

        description = self._input_desc.text().strip()

        recipe = build_recipe_from_state(
            name=name,
            description=description,
            file_entries=self._file_entries,
            cleansing_rules=self._cleansing_rules,
            join_type=self._join_type,
            normalize_keys=self._normalize_keys,
            cross_steps=self._cross_steps,
        )

        dest = self._recipes_dir / f"{recipe.recipe_id}.json"
        try:
            save_recipe(recipe, dest)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error al guardar",
                f"No se pudo guardar la receta.\n\nDetalle tecnico: {exc}",
            )
            return

        # Auditoria — RN-019: solo metadatos estructurales.
        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._current_user,
            accion="RECIPE_SAVE",
            extra={
                "recipe_name": name,
                "file_specs_count": len(self._file_entries),
                "rules_count": len(self._cleansing_rules),
                "cross_steps_count": len(self._cross_steps),
                "join_type": self._join_type,
            },
        ))

        QMessageBox.information(
            self,
            "Receta guardada",
            f"La receta '{name}' fue guardada correctamente.\n"
            f"La podras cargar la proxima vez desde la pantalla de carga.",
        )
        self.accept()


# ---------------------------------------------------------------------------
# LoadRecipeDialog
# ---------------------------------------------------------------------------

# Indices de vistas dentro del QStackedWidget interno.
_IDX_LIST = 0
_IDX_MAP  = 1


class _FileMapRow(QWidget):
    """
    Una fila de mapeo: label esperado | archivo seleccionado | [Seleccionar...]
    """

    def __init__(self, spec_label: str, spec_description: str, parent=None) -> None:
        super().__init__(parent)
        self._spec_label = spec_label
        self._selected_path: Path | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)

        lbl = QLabel(spec_label)
        lbl.setFixedWidth(160)
        lbl.setStyleSheet(
            f"font-weight: bold; color: {COLOR_PRIMARY}; font-size: 12px;"
        )
        layout.addWidget(lbl)

        self._lbl_file = QLabel("(ninguno)")
        self._lbl_file.setMinimumWidth(180)
        self._lbl_file.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        layout.addWidget(self._lbl_file)

        if spec_description:
            lbl_hint = QLabel(f"— {spec_description}")
            lbl_hint.setStyleSheet(
                f"color: {COLOR_TEXT_MID}; font-size: 10px; font-style: italic;"
            )
            layout.addWidget(lbl_hint)

        layout.addStretch()

        btn_select = QPushButton("Seleccionar…")
        btn_select.setStyleSheet(_STYLE_BTN_RECIPE)
        btn_select.clicked.connect(self._on_select)
        layout.addWidget(btn_select)

    def _on_select(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Seleccionar archivo para '{self._spec_label}'",
            "",
            "Archivos Excel (*.xlsx *.xls)",
        )
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() not in (".xlsx", ".xls"):
            QMessageBox.warning(
                self,
                "Formato no soportado",
                "Solo se aceptan archivos .xlsx y .xls.",
            )
            return
        self._selected_path = p
        self._lbl_file.setText(p.name)
        self._lbl_file.setStyleSheet(
            f"color: {COLOR_TEXT_DARK}; font-size: 11px; font-weight: bold;"
        )

    def get_path(self) -> Path | None:
        return self._selected_path

    def get_label(self) -> str:
        return self._spec_label


class LoadRecipeDialog(QDialog):
    """
    Dialogo modal de dos vistas para seleccionar y aplicar una receta.
    Vista 1: lista de recetas guardadas.
    Vista 2: mapeo de archivos nuevos a los labels de la receta.
    Emite recipe_loaded(Recipe, list[FileEntry]) al confirmar.
    """

    recipe_loaded = Signal(object, list)  # (Recipe, list[FileEntry])

    def __init__(
        self,
        recipes_dir: Path,
        reader: ExcelFileReader,
        audit_logger: AuditLogger,
        current_user: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._recipes_dir = recipes_dir
        self._reader = reader
        self._logger = audit_logger
        self._current_user = current_user
        self._selected_recipe: Recipe | None = None
        self._map_rows: list[_FileMapRow] = []

        self.setWindowTitle("Mis recetas")
        self.setMinimumWidth(600)
        self.setMinimumHeight(420)
        self.setModal(True)
        self._build_ui()
        self._populate_list()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        self._stack.addWidget(self._build_list_view())   # _IDX_LIST
        self._stack.addWidget(self._build_map_view())    # _IDX_MAP
        self._stack.setCurrentIndex(_IDX_LIST)

    # ------------------------------------------------------------------
    # Vista 1: lista de recetas
    # ------------------------------------------------------------------

    def _build_list_view(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Mis recetas")
        title.setStyleSheet(STYLE_SCREEN_TITLE)
        layout.addWidget(title)

        self._list_widget = QListWidget()
        self._list_widget.setStyleSheet(
            f"font-size: 12px; color: {COLOR_TEXT_DARK}; "
            f"border: 1.5px solid #ccd6e0; border-radius: 4px;"
        )
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.itemDoubleClicked.connect(self._on_select_recipe)
        layout.addWidget(self._list_widget, 1)

        # Mensaje cuando no hay recetas
        self._lbl_empty = QLabel(
            "No hay recetas guardadas todavia.\n"
            "Configura un cruce y guarda la receta desde la pantalla de cruce."
        )
        self._lbl_empty.setWordWrap(True)
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; font-size: 12px; font-style: italic;"
        )
        self._lbl_empty.hide()
        layout.addWidget(self._lbl_empty)

        btn_row = QHBoxLayout()

        self._btn_delete = QPushButton("Eliminar")
        self._btn_delete.setStyleSheet(
            f"color: {COLOR_ERROR}; border: 1.5px solid {COLOR_ERROR}; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        self._btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self._btn_delete)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #ccd6e0; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addStretch()

        self._btn_select = QPushButton("Seleccionar  →")
        self._btn_select.setMinimumHeight(38)
        self._btn_select.setStyleSheet(STYLE_BTN_PRIMARY + "font-size: 12px;")
        self._btn_select.clicked.connect(self._on_select_recipe)
        btn_row.addWidget(self._btn_select)

        layout.addLayout(btn_row)
        return w

    def _populate_list(self) -> None:
        self._list_widget.clear()
        recipes = list_recipes(self._recipes_dir)

        if not recipes:
            self._list_widget.hide()
            self._lbl_empty.show()
            self._btn_select.setEnabled(False)
            self._btn_delete.setEnabled(False)
            return

        self._list_widget.show()
        self._lbl_empty.hide()
        self._btn_select.setEnabled(True)
        self._btn_delete.setEnabled(True)

        for recipe in recipes:
            # Fecha compacta (primeros 10 caracteres del ISO: YYYY-MM-DD).
            date_str = recipe.updated_at[:10] if len(recipe.updated_at) >= 10 else recipe.updated_at
            text = f"{recipe.name}  [{date_str}]"
            if recipe.description:
                text += f"\n  {recipe.description}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, recipe)
            self._list_widget.addItem(item)

    def _on_select_recipe(self) -> None:
        item = self._list_widget.currentItem()
        if not item:
            QMessageBox.information(
                self,
                "Seleccion requerida",
                "Selecciona una receta de la lista.",
            )
            return
        self._selected_recipe = item.data(Qt.ItemDataRole.UserRole)
        self._build_map_rows()
        self._stack.setCurrentIndex(_IDX_MAP)

    def _on_delete(self) -> None:
        item = self._list_widget.currentItem()
        if not item:
            QMessageBox.information(
                self,
                "Seleccion requerida",
                "Selecciona una receta para eliminar.",
            )
            return
        recipe: Recipe = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self,
            "Confirmar eliminacion",
            f"Eliminar la receta '{recipe.name}'?\n\nEsta accion no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted = delete_recipe(recipe.recipe_id, self._recipes_dir)
        if deleted:
            self._populate_list()
        else:
            QMessageBox.warning(
                self,
                "No encontrada",
                "No se encontro el archivo de la receta. Es posible que ya haya sido eliminada.",
            )

    # ------------------------------------------------------------------
    # Vista 2: mapeo de archivos
    # ------------------------------------------------------------------

    def _build_map_view(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self._map_title = QLabel("Cargar receta")
        self._map_title.setStyleSheet(STYLE_SCREEN_TITLE)
        layout.addWidget(self._map_title)

        self._map_desc = QLabel("")
        self._map_desc.setWordWrap(True)
        self._map_desc.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; font-size: 12px; font-style: italic;"
        )
        layout.addWidget(self._map_desc)

        lbl_instr = QLabel(
            "Selecciona el archivo a cargar para cada etiqueta que necesita la receta:"
        )
        lbl_instr.setWordWrap(True)
        lbl_instr.setStyleSheet(f"color: {COLOR_TEXT_DARK}; font-size: 12px;")
        layout.addWidget(lbl_instr)

        # Scroll con filas de mapeo
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: #f9fbfd;")

        self._map_container = QWidget()
        self._map_container.setStyleSheet("background-color: #f9fbfd;")
        self._map_layout = QVBoxLayout(self._map_container)
        self._map_layout.setSpacing(4)
        self._map_layout.setContentsMargins(4, 4, 4, 4)
        self._map_layout.addStretch()

        scroll.setWidget(self._map_container)
        layout.addWidget(scroll, 1)

        # Botones
        btn_row = QHBoxLayout()

        btn_back = QPushButton("← Volver")
        btn_back.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #ccd6e0; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        btn_back.clicked.connect(lambda: self._stack.setCurrentIndex(_IDX_LIST))
        btn_row.addWidget(btn_back)

        btn_cancel2 = QPushButton("Cancelar")
        btn_cancel2.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; border: 1.5px solid #ccd6e0; "
            f"border-radius: 4px; padding: 4px 14px;"
        )
        btn_cancel2.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel2)

        btn_row.addStretch()

        self._btn_load = QPushButton("Cargar y continuar  →")
        self._btn_load.setMinimumHeight(38)
        self._btn_load.setStyleSheet(STYLE_BTN_PRIMARY + "font-size: 12px;")
        self._btn_load.clicked.connect(self._on_load_and_continue)
        btn_row.addWidget(self._btn_load)

        layout.addLayout(btn_row)
        return w

    def _build_map_rows(self) -> None:
        """Reconstruye las filas de mapeo para la receta seleccionada."""
        # Limpiar filas anteriores (sin tocar el stretch).
        for row in self._map_rows:
            self._map_layout.removeWidget(row)
            row.deleteLater()
        self._map_rows.clear()

        if not self._selected_recipe:
            return

        recipe = self._selected_recipe
        self._map_title.setText(f"Cargar receta: {recipe.name}")
        self._map_desc.setText(recipe.description or "")

        for spec in recipe.file_specs:
            row = _FileMapRow(
                spec_label=spec.label,
                spec_description=spec.description,
            )
            self._map_rows.append(row)
            self._map_layout.insertWidget(self._map_layout.count() - 1, row)

    def _on_load_and_continue(self) -> None:
        if not self._selected_recipe:
            return

        # Verificar que todos los archivos fueron seleccionados.
        missing = [r.get_label() for r in self._map_rows if r.get_path() is None]
        if missing:
            QMessageBox.warning(
                self,
                "Archivos faltantes",
                "Selecciona un archivo para cada etiqueta:\n\n"
                + "\n".join(f"  • {lbl}" for lbl in missing),
            )
            return

        # Leer cada archivo.
        file_entries: list[FileEntry] = []
        errors: list[str] = []

        for row in self._map_rows:
            path = row.get_path()
            label = row.get_label()
            if path is None:
                continue
            try:
                df, metadata = self._reader.read(path, sheet_index=-1)
                from data.models import FileEntry, FileMetadata
                entry = FileEntry(
                    path=path,
                    label=label,
                    sheet_index=-1,
                    df=df,
                    metadata=metadata,
                )
                file_entries.append(entry)
            except (FileReadError, EmptyFileError) as exc:
                errors.append(f"{label}: {exc}")

        if errors:
            QMessageBox.warning(
                self,
                "Problemas al cargar archivos",
                "No se pudieron cargar algunos archivos:\n\n"
                + "\n".join(f"• {e}" for e in errors),
            )
            return

        # Validar receta contra los archivos cargados.
        recipe = self._selected_recipe
        warnings = validate_recipe_against_entries(recipe, file_entries)
        if warnings:
            reply = QMessageBox.question(
                self,
                "Advertencias de compatibilidad",
                "Se encontraron las siguientes advertencias:\n\n"
                + "\n".join(f"• {w}" for w in warnings)
                + "\n\n¿Continuar de todos modos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Auditoria — RN-019: solo metadatos estructurales.
        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._current_user,
            accion="RECIPE_LOAD",
            extra={
                "recipe_name": recipe.name,
                "files_mapped": len(file_entries),
                "warnings_count": len(warnings),
            },
        ))

        self.recipe_loaded.emit(recipe, file_entries)
        self.accept()
