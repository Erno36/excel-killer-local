"""
ui/stats_panel.py — Panel colapsable de estadisticas del resultado.

QThread worker para calculo no-bloqueante (RT-STATS-02).
RN-019: el log de auditoria solo contiene nombres de columnas y conteos
        agregados, nunca valores de celdas individuales.
RN-STATS-003: no se loggean sumas, promedios, min/max ni fechas extremas.
"""
from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from engine.stats import compute_stats, StatsResult


# ---------------------------------------------------------------------------
# Worker (hilo de calculo)
# ---------------------------------------------------------------------------

class StatsWorker(QThread):
    """
    Hilo de computo de estadisticas. Emite stats_ready cuando termina.
    Emite error_occurred si falla.
    """

    stats_ready = Signal(object)    # StatsResult
    error_occurred = Signal(str)

    def __init__(
        self,
        df: pd.DataFrame,
        matched_rows: int | None,
        left_only_rows: int | None,
        right_only_rows: int | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._df = df.copy()   # copia para thread safety
        self._matched = matched_rows
        self._left_only = left_only_rows
        self._right_only = right_only_rows

    def run(self) -> None:
        try:
            result = compute_stats(
                self._df,
                matched_rows=self._matched,
                left_only_rows=self._left_only,
                right_only_rows=self._right_only,
            )
            self.stats_ready.emit(result)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


# ---------------------------------------------------------------------------
# Panel colapsable
# ---------------------------------------------------------------------------

class StatsPanel(QFrame):
    """
    Panel colapsable de estadisticas. Se muestra/oculta desde ResultScreen
    con el boton toggle externo.

    set_data() prepara los datos sin calcular.
    El usuario presiona "Calcular" para disparar el StatsWorker.

    stats_computed: Signal(StatsResult) — emitido al terminar para audit log.
    stats_invalidated: Signal() — emitido cuando los datos cambian (working_df reset).
    """

    stats_computed = Signal(object)    # emite StatsResult — solo para audit (RN-STATS-003)
    stats_invalidated = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: StatsWorker | None = None
        self._result_ready: bool = False
        self._build_ui()
        self.hide()

    # ------------------------------------------------------------------
    # Construccion de la UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        from ui.login_screen import (
            COLOR_PRIMARY,
            COLOR_PRIMARY_LIGHT,
            COLOR_TEXT_MID,
        )

        self.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_PRIMARY_LIGHT}; "
            f"border: 1px solid #c8d8ea; border-radius: 6px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # --- Fila de cabecera ---
        header_row = QHBoxLayout()

        title = QLabel("Estadisticas del resultado")
        title.setStyleSheet(
            f"font-weight: bold; color: {COLOR_PRIMARY}; font-size: 13px;"
        )
        header_row.addWidget(title)
        header_row.addStretch()

        self._btn_compute = QPushButton("Calcular")
        self._btn_compute.setFixedHeight(26)
        self._btn_compute.setStyleSheet(
            f"background-color: {COLOR_PRIMARY}; color: white; "
            f"border-radius: 4px; padding: 2px 12px; font-size: 11px; font-weight: bold;"
        )
        self._btn_compute.clicked.connect(self._on_compute_clicked)
        header_row.addWidget(self._btn_compute)

        outer.addLayout(header_row)

        # --- Barra de progreso (indeterminada, oculta por defecto) ---
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminada
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet(
            f"QProgressBar {{ border: none; background: #e0eaf4; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {COLOR_PRIMARY}; border-radius: 3px; }}"
        )
        self._progress.hide()
        outer.addWidget(self._progress)

        # --- Label de resumen ---
        self._lbl_summary = QLabel("(Presiona Calcular para ver estadisticas)")
        self._lbl_summary.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; font-size: 11px; font-style: italic;"
        )
        outer.addWidget(self._lbl_summary)

        # --- Tabla de columnas ---
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels([
            "Columna", "Tipo", "Nulos", "% Nulos", "Únicos",
            "Mín / Fecha desde", "Máx / Fecha hasta", "Suma / Promedio",
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setMinimumHeight(120)
        self._table.setStyleSheet(
            "font-size: 11px; "
            f"QHeaderView::section {{ background-color: #d8e8f4; "
            f"color: {COLOR_PRIMARY}; font-weight: bold; padding: 3px; }}"
        )
        self._table.hide()
        outer.addWidget(self._table)

        # --- Nota RN-019 ---
        lbl_note = QLabel(
            "Las estadisticas son conteos agregados. "
            "Ningun valor individual queda registrado en el log de auditoria."
        )
        lbl_note.setWordWrap(True)
        lbl_note.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; font-size: 10px; font-style: italic;"
        )
        outer.addWidget(lbl_note)

        # Nota sobre working_df vs filtros.
        lbl_scope = QLabel(
            "Nota: las estadisticas corresponden a todas las filas del resultado, "
            "independientemente de los filtros activos en la tabla."
        )
        lbl_scope.setWordWrap(True)
        lbl_scope.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; font-size: 10px; font-style: italic;"
        )
        outer.addWidget(lbl_scope)

        # Referencias internas (seteadas desde ResultScreen).
        self._df: pd.DataFrame | None = None
        self._matched_rows: int | None = None
        self._left_only_rows: int | None = None
        self._right_only_rows: int | None = None

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------

    def set_data(
        self,
        df: pd.DataFrame,
        matched_rows: int | None,
        left_only_rows: int | None,
        right_only_rows: int | None,
    ) -> None:
        """
        Actualiza los datos a analizar. Resetea el estado del panel.
        No calcula nada: el usuario debe presionar "Calcular".
        """
        # Cancelar worker en curso si hay uno.
        if self._worker is not None and self._worker.isRunning():
            self._worker.stats_ready.disconnect()
            self._worker.error_occurred.disconnect()
            self._worker.requestInterruption()

        self._df = df
        self._matched_rows = matched_rows
        self._left_only_rows = left_only_rows
        self._right_only_rows = right_only_rows
        self._result_ready = False

        # Resetear UI.
        self._table.setRowCount(0)
        self._table.hide()
        self._lbl_summary.setText("(Presiona Calcular para ver estadisticas)")

        from ui.login_screen import COLOR_TEXT_MID
        self._lbl_summary.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; font-size: 11px; font-style: italic;"
        )
        self._btn_compute.setText("Calcular")
        self._btn_compute.setEnabled(True)

    def invalidate(self) -> None:
        """
        Invalida el panel cuando el working_df cambia
        (Restaurar original, borrado de filas/columnas).
        Muestra aviso de que hay que recalcular.
        """
        if self._result_ready:
            from ui.login_screen import COLOR_WARNING
            self._lbl_summary.setText(
                "Los datos cambiaron. Recalcula las estadisticas."
            )
            self._lbl_summary.setStyleSheet(
                f"color: {COLOR_WARNING}; font-size: 11px; font-weight: bold;"
            )
            self._table.hide()
            self._btn_compute.setText("Calcular")
            self._btn_compute.setEnabled(True)
            self._result_ready = False
            self.stats_invalidated.emit()

    # ------------------------------------------------------------------
    # Slots internos
    # ------------------------------------------------------------------

    def _on_compute_clicked(self) -> None:
        if self._df is None:
            return
        if len(self._df) == 0:
            self._lbl_summary.setText("No hay datos en el resultado para analizar.")
            return

        self._btn_compute.setEnabled(False)
        self._progress.show()
        self._lbl_summary.setText("Calculando...")

        from ui.login_screen import COLOR_TEXT_MID
        self._lbl_summary.setStyleSheet(
            f"color: {COLOR_TEXT_MID}; font-size: 11px; font-style: italic;"
        )

        self._worker = StatsWorker(
            df=self._df,
            matched_rows=self._matched_rows,
            left_only_rows=self._left_only_rows,
            right_only_rows=self._right_only_rows,
            parent=self,
        )
        self._worker.stats_ready.connect(self._on_stats_ready)
        self._worker.error_occurred.connect(self._on_stats_error)
        self._worker.finished.connect(lambda: self._progress.hide())
        self._worker.start()

    def _on_stats_ready(self, result: StatsResult) -> None:
        self._result_ready = True
        self._btn_compute.setText("Recalcular")
        self._btn_compute.setEnabled(True)
        self._progress.hide()

        # Construir texto de resumen.
        summary_parts = [
            f"Total: {result.total_rows:,} filas  |  {result.total_cols} columnas"
        ]
        if result.matched_rows is not None:
            summary_parts.append(f"Coincidencias: {result.matched_rows:,}")
        if result.left_only_rows is not None:
            summary_parts.append(f"Solo izquierda: {result.left_only_rows:,}")
        if result.right_only_rows is not None:
            summary_parts.append(f"Solo derecha: {result.right_only_rows:,}")
        summary_parts.append(f"Calculado en {result.duration_ms:.0f} ms")

        self._lbl_summary.setText("  |  ".join(summary_parts))
        self._lbl_summary.setStyleSheet("color: #1a5276; font-size: 11px;")

        # Poblar tabla de columnas.
        self._table.setRowCount(0)
        for cs in result.columns:
            row = self._table.rowCount()
            self._table.insertRow(row)

            self._table.setItem(row, 0, QTableWidgetItem(cs.name))
            self._table.setItem(row, 1, QTableWidgetItem(cs.dtype_label))
            self._table.setItem(row, 2, QTableWidgetItem(str(cs.null_count)))
            self._table.setItem(row, 3, QTableWidgetItem(f"{cs.null_pct:.1f}%"))
            self._table.setItem(row, 4, QTableWidgetItem(str(cs.unique_count)))

            if cs.dtype_label == "numero":
                min_text = f"{cs.num_min:,.2f}" if cs.num_min is not None else "—"
                max_text = f"{cs.num_max:,.2f}" if cs.num_max is not None else "—"
                if cs.num_sum is not None and cs.num_mean is not None:
                    suma_prom = f"S: {cs.num_sum:,.2f} / P: {cs.num_mean:,.2f}"
                elif cs.num_sum is not None:
                    suma_prom = f"S: {cs.num_sum:,.2f}"
                else:
                    suma_prom = "—"
                self._table.setItem(row, 5, QTableWidgetItem(min_text))
                self._table.setItem(row, 6, QTableWidgetItem(max_text))
                self._table.setItem(row, 7, QTableWidgetItem(suma_prom))
            elif cs.dtype_label == "fecha":
                self._table.setItem(row, 5, QTableWidgetItem(cs.date_min or "—"))
                self._table.setItem(row, 6, QTableWidgetItem(cs.date_max or "—"))
                self._table.setItem(row, 7, QTableWidgetItem("—"))
            elif cs.dtype_label == "identificador":
                self._table.setItem(row, 5, QTableWidgetItem("(omitido)"))
                self._table.setItem(row, 6, QTableWidgetItem("(omitido)"))
                self._table.setItem(row, 7, QTableWidgetItem("(omitido)"))
            else:
                self._table.setItem(row, 5, QTableWidgetItem("—"))
                self._table.setItem(row, 6, QTableWidgetItem("—"))
                self._table.setItem(row, 7, QTableWidgetItem("—"))

        self._table.resizeColumnsToContents()
        self._table.show()

        # Emitir para audit log (RN-STATS-003: solo metadata, sin valores).
        self.stats_computed.emit(result)

    def _on_stats_error(self, msg: str) -> None:
        self._btn_compute.setEnabled(True)
        self._progress.hide()
        self._lbl_summary.setText(
            f"No se pudieron calcular las estadisticas. Ver logs para el detalle."
        )
        from ui.login_screen import COLOR_ERROR
        self._lbl_summary.setStyleSheet(
            f"color: {COLOR_ERROR}; font-size: 11px;"
        )

    # ------------------------------------------------------------------
    # Datos para audit log
    # ------------------------------------------------------------------

    def emit_audit_data(self, result: StatsResult) -> dict:
        """
        Retorna dict con datos para el log de auditoria.
        RN-019 / RN-STATS-003: solo conteos y nombres de columnas.
        NO incluye sumas, promedios, min/max de numericos ni fechas extremas.
        """
        return {
            "total_rows": result.total_rows,
            "total_cols": result.total_cols,
            "matched_rows": result.matched_rows,
            "left_only_rows": result.left_only_rows,
            "right_only_rows": result.right_only_rows,
            "columnas_analizadas": [cs.name for cs in result.columns],
            "duration_ms": round(result.duration_ms, 1),
        }
