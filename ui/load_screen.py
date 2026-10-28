"""
ui/load_screen.py — Pantalla de carga de archivos.

HU-02: carga dinamica de N archivos con etiqueta libre y selector de hoja.
HU-03: deteccion automatica de columnas al cargar cada archivo.
Opcion "Todas las hojas": lee y concatena todas las hojas del archivo (sheet_index=-1).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import pandas as pd

from audit.logger import AuditLogger, make_timestamp
from data.models import AuditEntry, CrossResult, FileEntry, FileMetadata
from engine.reader import EmptyFileError, ExcelFileReader, FileReadError
from ui.login_screen import (
    COLOR_ERROR,
    COLOR_PRIMARY,
    COLOR_TEXT_DARK,
    COLOR_TEXT_MID,
    STYLE_BTN_PRIMARY,
    STYLE_SCREEN_TITLE,
)

# Primer item del combo de hojas: sentinel para "leer todas".
_TODAS_LAS_HOJAS = "— Todas las hojas —"


class FileRow(QWidget):
    """
    Una fila de la pantalla de carga.
    Contiene archivo, etiqueta, hoja, seleccion de fila de encabezado y boton quitar.
    """

    removed = Signal(object)  # emite self

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._sheet_names: list[str] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        self._btn_open = QPushButton("Seleccionar archivo…")
        self._btn_open.setMinimumWidth(180)
        self._btn_open.setStyleSheet(
            f"border: 1.5px solid {COLOR_PRIMARY}; color: {COLOR_PRIMARY}; "
            f"border-radius: 4px; padding: 4px 8px; font-weight: bold;"
        )
        self._btn_open.clicked.connect(self._on_open)
        layout.addWidget(self._btn_open)

        self._lbl_filename = QLabel("(ninguno)")
        self._lbl_filename.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        self._lbl_filename.setMinimumWidth(140)
        layout.addWidget(self._lbl_filename)

        self._input_label = QLineEdit()
        self._input_label.setPlaceholderText("Etiqueta (ej: Stock Seguros)")
        self._input_label.setMinimumWidth(160)
        self._input_label.setStyleSheet(
            f"border: 1.5px solid #ccd6e0; border-radius: 4px; "
            f"padding: 3px 8px; color: {COLOR_TEXT_DARK};"
        )
        layout.addWidget(self._input_label)

        self._combo_sheet = QComboBox()
        self._combo_sheet.setMinimumWidth(150)
        self._combo_sheet.setEnabled(False)
        self._combo_sheet.currentIndexChanged.connect(self._update_header_options)
        layout.addWidget(self._combo_sheet)

        self._combo_header = QComboBox()
        self._combo_header.setMinimumWidth(150)
        self._combo_header.addItem("Detectar automaticamente", None)
        self._combo_header.setEnabled(False)
        self._combo_header.setToolTip(
            "La aplicacion busca el encabezado entre las primeras 20 filas. "
            "Si hace falta, elegi otra fila."
        )
        layout.addWidget(self._combo_header)

        self._btn_remove = QPushButton("✕")
        self._btn_remove.setFixedWidth(32)
        self._btn_remove.setFixedHeight(32)
        self._btn_remove.setStyleSheet(
            f"color: {COLOR_ERROR}; font-weight: bold; font-size: 14px; "
            f"border: 1.5px solid {COLOR_ERROR}; border-radius: 4px; "
            f"background: white;"
        )
        self._btn_remove.setToolTip("Quitar este archivo")
        self._btn_remove.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self._btn_remove)

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo Excel",
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
        self._path = p
        self._lbl_filename.setText(p.name)
        if not self._input_label.text().strip():
            self._input_label.setText(p.stem)
        self._load_sheets(p)

    def _load_sheets(self, path: Path) -> None:
        import pandas as pd
        try:
            engine = "openpyxl" if path.suffix.lower() == ".xlsx" else "xlrd"
            xl = pd.ExcelFile(str(path), engine=engine)
            self._sheet_names = xl.sheet_names
        except Exception:
            self._sheet_names = []

        self._combo_sheet.clear()
        if self._sheet_names:
            # Primer item: sentinel para leer todas las hojas.
            self._combo_sheet.addItem(_TODAS_LAS_HOJAS)
            self._combo_sheet.addItems(self._sheet_names)
            # Siempre defecto "Todas las hojas" — el usuario elige hoja específica si quiere.
            self._combo_sheet.setCurrentIndex(0)
            self._combo_sheet.setEnabled(True)
        else:
            self._combo_sheet.setEnabled(False)
        self._update_header_options()

    def _update_header_options(self, *_args) -> None:
        self._combo_header.clear()
        self._combo_header.addItem("Detectar automaticamente", None)
        if self._path is None or not self._combo_sheet.isEnabled():
            self._combo_header.setEnabled(False)
            return

        sheet_index = self.get_sheet_index()
        if sheet_index == -1:
            if len(self._sheet_names) == 1:
                sheet_index = 0
            else:
                self._combo_header.setEnabled(False)
                self._combo_header.setToolTip(
                    "Con todas las hojas, el encabezado se detecta por separado en cada hoja."
                )
                return

        try:
            candidates, scanned_rows = ExcelFileReader().inspect_header_rows(
                self._path,
                sheet_index=sheet_index,
            )
        except FileReadError:
            self._combo_header.setEnabled(False)
            self._combo_header.setToolTip(
                "No se pudieron inspeccionar los encabezados. Se informara el error al cargar."
            )
            return

        if candidates:
            self._combo_header.setItemText(
                0, f"Detectar automaticamente (sugerida: fila {candidates[0] + 1})"
            )
        for row_index in range(scanned_rows):
            self._combo_header.addItem(f"Fila {row_index + 1}", row_index)
        self._combo_header.setEnabled(True)
        self._combo_header.setToolTip(
            "La aplicacion busca el encabezado entre las primeras 20 filas. "
            "Si hace falta, elegi otra fila."
        )

    def get_path(self) -> Path | None:
        return self._path

    def get_label(self) -> str:
        label = self._input_label.text().strip()
        if not label and self._path:
            return self._path.stem
        return label

    def get_sheet_index(self) -> int:
        """
        Retorna el indice de la hoja seleccionada.
        -1 = "Todas las hojas" (sentinel para leer y concatenar todas).
        0..N-1 = hoja especifica.
        """
        if not self._combo_sheet.isEnabled():
            return 0
        combo_idx = self._combo_sheet.currentIndex()
        if combo_idx == 0:
            return -1  # "Todas las hojas"
        return combo_idx - 1  # offset por el item sentinel al inicio

    def get_header_row(self) -> int | None:
        """Retorna fila de encabezado 0-based o None para deteccion automatica."""
        value = self._combo_header.currentData()
        return value if isinstance(value, int) else None


class VirtualFileRow(QWidget):
    """
    Fila de archivo virtual — resultado de un cruce previo.
    No tiene selector de archivo ni de hoja. Solo muestra info y permite editar la etiqueta.
    """

    removed = Signal(object)  # emite self

    def __init__(self, entry: FileEntry, parent=None) -> None:
        super().__init__(parent)
        self._entry = entry

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        # Badge identificatorio
        badge = QLabel("⟳ Resultado previo")
        badge.setFixedWidth(180)
        badge.setStyleSheet(
            "color: #7b3f00; background-color: #fff3e0; "
            "border: 1.5px solid #e67e22; border-radius: 4px; "
            "padding: 4px 8px; font-weight: bold; font-size: 11px;"
        )
        layout.addWidget(badge)

        # Info de columnas
        cols = len(entry.df.columns) if entry.df is not None else 0
        rows = entry.metadata.row_count
        lbl_info = QLabel(f"{rows:,} filas · {cols} cols")
        lbl_info.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 11px;")
        lbl_info.setMinimumWidth(140)
        layout.addWidget(lbl_info)

        # Etiqueta editable
        self._input_label = QLineEdit(entry.label)
        self._input_label.setPlaceholderText("Etiqueta para este resultado")
        self._input_label.setMinimumWidth(160)
        self._input_label.setStyleSheet(
            f"border: 1.5px solid #e67e22; border-radius: 4px; "
            f"padding: 3px 8px; color: {COLOR_TEXT_DARK};"
        )
        layout.addWidget(self._input_label)

        # Espacio donde iría el combo de hojas (vacío para mantener alineación)
        spacer = QLabel("(en memoria)")
        spacer.setMinimumWidth(150)
        spacer.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 10px; font-style: italic;")
        layout.addWidget(spacer)

        header_spacer = QLabel("—")
        header_spacer.setMinimumWidth(150)
        header_spacer.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 10px;")
        layout.addWidget(header_spacer)

        # Botón quitar
        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(32)
        btn_remove.setFixedHeight(32)
        btn_remove.setStyleSheet(
            f"color: {COLOR_ERROR}; font-weight: bold; font-size: 14px; "
            f"border: 1.5px solid {COLOR_ERROR}; border-radius: 4px; background: white;"
        )
        btn_remove.setToolTip("Quitar este resultado de la lista")
        btn_remove.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(btn_remove)

    def get_entry(self) -> FileEntry:
        """Devuelve el FileEntry actualizado con la etiqueta actual."""
        label = self._input_label.text().strip() or self._entry.label
        from dataclasses import replace
        return replace(self._entry, label=label)


class LoadScreen(QWidget):
    """
    Pantalla de carga de archivos.
    Emite files_confirmed(list[FileEntry]) cuando el usuario acepta.
    Emite recipe_applied(Recipe, list[FileEntry]) cuando el usuario carga una receta.
    """

    files_confirmed = Signal(list)   # list[FileEntry]
    recipe_applied  = Signal(object, list)  # (Recipe, list[FileEntry])

    def __init__(
        self,
        audit_logger: AuditLogger,
        username: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._logger = audit_logger
        self._username = username
        self._reader = ExcelFileReader()
        self._rows: list[FileRow] = []
        self._virtual_rows: list[VirtualFileRow] = []

        self._build_ui()
        self._add_row()
        self._add_row()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 16, 24, 16)
        main_layout.setSpacing(12)

        # --- Titulo de pantalla ---
        header = QLabel("Carga de archivos")
        header.setStyleSheet(STYLE_SCREEN_TITLE)
        main_layout.addWidget(header)

        desc = QLabel(
            "Seleccioná los archivos Excel a cruzar y asigná una etiqueta a cada uno. "
            "Se necesitan al menos 2 archivos."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_TEXT_MID}; font-size: 12px;")
        main_layout.addWidget(desc)

        # --- Encabezado de columnas (sobre fondo azul) ---
        col_header = QFrame()
        col_header.setStyleSheet(
            f"background-color: {COLOR_PRIMARY}; border-radius: 4px; padding: 2px;"
        )
        col_layout = QHBoxLayout(col_header)
        col_layout.setContentsMargins(8, 4, 8, 4)
        col_layout.setSpacing(0)

        col_specs = [
            ("Archivo", 188),
            ("Nombre del archivo", 148),
            ("Etiqueta", 168),
            ("Hoja a leer", 158),
            ("Encabezado", 150),
            ("", 40),
        ]
        for label, width in col_specs:
            lbl = QLabel(label)
            lbl.setFixedWidth(width)
            lbl.setStyleSheet(
                "color: white; font-weight: bold; font-size: 11px; background: transparent;"
            )
            col_layout.addWidget(lbl)

        col_layout.addStretch()
        main_layout.addWidget(col_header)

        # --- Area de scroll para filas de archivos ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: #f9fbfd;")

        self._rows_container = QWidget()
        self._rows_container.setStyleSheet("background-color: #f9fbfd;")
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setSpacing(2)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.addStretch()

        scroll.setWidget(self._rows_container)
        main_layout.addWidget(scroll, 1)

        # --- Botones ---
        btn_row = QHBoxLayout()

        btn_add = QPushButton("＋  Agregar archivo")
        btn_add.setMinimumHeight(36)
        btn_add.setStyleSheet(
            f"color: {COLOR_PRIMARY}; border: 1.5px solid {COLOR_PRIMARY}; "
            f"border-radius: 4px; font-weight: bold; padding: 4px 14px;"
        )
        btn_add.clicked.connect(self._add_row)
        btn_row.addWidget(btn_add)

        _COLOR_RECIPE = "#e67e22"
        btn_recipe = QPushButton("Cargar receta")
        btn_recipe.setMinimumHeight(36)
        btn_recipe.setStyleSheet(
            f"color: {_COLOR_RECIPE}; border: 1.5px solid {_COLOR_RECIPE}; "
            f"border-radius: 4px; font-weight: bold; padding: 4px 14px;"
        )
        btn_recipe.setToolTip(
            "Cargar una receta guardada para reutilizar el flujo de limpieza y cruce."
        )
        btn_recipe.clicked.connect(self._on_load_recipe)
        btn_row.addWidget(btn_recipe)

        btn_row.addStretch()

        self._btn_accept = QPushButton("Continuar →")
        self._btn_accept.setMinimumHeight(42)
        self._btn_accept.setStyleSheet(STYLE_BTN_PRIMARY + "font-size: 13px;")
        self._btn_accept.clicked.connect(self._on_accept)
        btn_row.addWidget(self._btn_accept)

        main_layout.addLayout(btn_row)

    def _add_row(self) -> None:
        row = FileRow()
        row.removed.connect(self._remove_row)
        self._rows.append(row)
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    def _remove_row(self, row: FileRow) -> None:
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()

    def _on_accept(self) -> None:
        entries: list[FileEntry] = []
        errors: list[str] = []

        # Incluir primero las entradas virtuales (resultados previos)
        for vrow in self._virtual_rows:
            entries.append(vrow.get_entry())

        rows_with_file = [r for r in self._rows if r.get_path() is not None]

        total_available = len(rows_with_file) + len(self._virtual_rows)
        if total_available < 2:
            QMessageBox.warning(
                self,
                "Archivos insuficientes",
                "Seleccioná al menos 2 archivos para continuar.",
            )
            return

        for row in rows_with_file:
            path = row.get_path()
            label = row.get_label() or (path.stem if path else "sin_etiqueta")
            sheet_index = row.get_sheet_index()  # -1 = todas las hojas

            try:
                df, metadata = self._reader.read(
                    path,
                    sheet_index=sheet_index,
                    header_row=row.get_header_row(),
                )

                self._logger.log(AuditEntry(
                    timestamp=make_timestamp(),
                    usuario=self._username,
                    accion="FILE_LOAD",
                    archivos=[{"nombre": path.name, "etiqueta": label}],
                    columnas=metadata.column_names,
                    filas_procesadas=metadata.row_count,
                ))

                self._logger.log(AuditEntry(
                    timestamp=make_timestamp(),
                    usuario=self._username,
                    accion="COLUMN_DETECT",
                    archivos=[{"nombre": path.name, "etiqueta": label}],
                    columnas=metadata.column_names,
                    filas_procesadas=metadata.row_count,
                    mensaje_error=(
                        "; ".join(metadata.warnings) if metadata.warnings else None
                    ),
                ))

                entry = FileEntry(
                    path=path,
                    label=label,
                    sheet_index=sheet_index,
                    df=df,
                    metadata=metadata,
                )
                entries.append(entry)

                if metadata.warnings:
                    QMessageBox.information(
                        self,
                        f"Aviso al cargar '{path.name}'",
                        "\n".join(f"• {w}" for w in metadata.warnings),
                    )

            except EmptyFileError as exc:
                errors.append(str(exc))
                self._logger.log(AuditEntry(
                    timestamp=make_timestamp(),
                    usuario=self._username,
                    accion="ERROR",
                    archivos=[{"nombre": path.name if path else "", "etiqueta": label}],
                    mensaje_error=str(exc),
                ))
            except FileReadError as exc:
                errors.append(str(exc))
                self._logger.log(AuditEntry(
                    timestamp=make_timestamp(),
                    usuario=self._username,
                    accion="ERROR",
                    archivos=[{"nombre": path.name if path else "", "etiqueta": label}],
                    mensaje_error=str(exc),
                ))

        if errors:
            QMessageBox.warning(
                self,
                "Problemas al cargar archivos",
                "No se pudieron cargar los siguientes archivos:\n\n"
                + "\n".join(f"• {e}" for e in errors),
            )

        if len(entries) < 2:
            QMessageBox.warning(
                self,
                "Archivos insuficientes",
                "Se necesitan al menos 2 archivos válidos para continuar.\n"
                "Revisá que los archivos no estén vacíos o dañados.",
            )
            return

        self.files_confirmed.emit(entries)

    def preload_result(self, result: CrossResult, label: str = "Resultado previo") -> None:
        """
        Agrega un resultado de cruce previo como archivo virtual en la lista.
        Permite cruces secuenciales: A⋈B → C, luego C⋈D → E.
        """
        if result.df is None or result.df.empty:
            return

        metadata = FileMetadata(
            path=None,  # type: ignore[arg-type]
            sheet_names=[],
            sheet_used="(memoria)",
            row_count=len(result.df),
            column_names=list(result.df.columns),
            warnings=[],
        )
        entry = FileEntry(
            path=None,
            label=label,
            sheet_index=0,
            df=result.df.copy(),
            metadata=metadata,
            is_virtual=True,
        )
        vrow = VirtualFileRow(entry)
        vrow.removed.connect(self._remove_virtual_row)
        self._virtual_rows.append(vrow)
        # Insertar al inicio del contenedor (antes de las filas normales)
        self._rows_layout.insertWidget(0, vrow)
        vrow.show()

        self._logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario=self._username,
            accion="FILE_LOAD",
            archivos=[{"nombre": "[resultado_previo]", "etiqueta": label}],
            columnas=metadata.column_names,
            filas_procesadas=metadata.row_count,
        ))

    def _remove_virtual_row(self, vrow: VirtualFileRow) -> None:
        if vrow in self._virtual_rows:
            self._virtual_rows.remove(vrow)
        self._rows_layout.removeWidget(vrow)
        vrow.deleteLater()

    def set_username(self, username: str) -> None:
        """Actualiza el usuario activo para los registros de auditoria."""
        self._username = username

    def reset(self) -> None:
        """Limpia todas las filas (normales y virtuales) y vuelve al estado inicial."""
        for vrow in self._virtual_rows[:]:
            self._rows_layout.removeWidget(vrow)
            vrow.deleteLater()
        self._virtual_rows.clear()

        for row in self._rows[:]:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._add_row()
        self._add_row()

    def _on_load_recipe(self) -> None:
        """Abre el dialogo de carga de receta y emite recipe_applied si el usuario confirma."""
        from config import config
        from ui.recipe_dialog import LoadRecipeDialog

        dlg = LoadRecipeDialog(
            recipes_dir=config.recipes_dir,
            reader=self._reader,
            audit_logger=self._logger,
            current_user=self._username,
            parent=self,
        )
        dlg.recipe_loaded.connect(self._on_recipe_loaded_from_dialog)
        dlg.exec()

    def _on_recipe_loaded_from_dialog(self, recipe, file_entries: list) -> None:
        """Propaga la senal al main_window."""
        self.recipe_applied.emit(recipe, file_entries)
