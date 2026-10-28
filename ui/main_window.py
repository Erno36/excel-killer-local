"""
ui/main_window.py — Ventana principal de la aplicacion.

Gestiona la navegacion entre pantallas y el timeout de sesion (RN-005).
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from audit.logger import AuditLogger, make_timestamp
from auth.service import SessionManager
from data.models import AuditEntry, CleansingRule, CrossResult, FileEntry, Recipe, User
import pandas as pd
from ui.load_screen import LoadScreen
from ui.cleansing_screen import CleansingScreen
from ui.cross_screen import CrossScreen
from ui.rules_screen import RulesScreen
from ui.result_screen import ResultScreen


# Indices de pantallas en el QStackedWidget.
IDX_LOAD   = 0
IDX_CLEAN  = 1
IDX_CROSS  = 2
IDX_RULES  = 3
IDX_RESULT = 4


class MainWindow(QMainWindow):
    """
    Shell principal. Contiene el QStackedWidget con las tres pantallas operativas.
    El Login se abre como dialogo modal antes de mostrar esta ventana.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        audit_logger: AuditLogger,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session = session_manager
        self._logger = audit_logger

        self.setWindowTitle("Cruzador Excel — Banco Piano")
        self.setMinimumSize(900, 620)

        # Stack de pantallas.
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._load_screen      = LoadScreen(audit_logger=self._logger)
        self._cleansing_screen = CleansingScreen(audit_logger=self._logger)
        self._cross_screen     = CrossScreen(audit_logger=self._logger)
        self._rules_screen     = RulesScreen(audit_logger=self._logger)
        self._result_screen    = ResultScreen(audit_logger=self._logger)

        self._stack.addWidget(self._load_screen)       # IDX_LOAD   = 0
        self._stack.addWidget(self._cleansing_screen)  # IDX_CLEAN  = 1
        self._stack.addWidget(self._cross_screen)      # IDX_CROSS  = 2
        self._stack.addWidget(self._rules_screen)      # IDX_RULES  = 3
        self._stack.addWidget(self._result_screen)     # IDX_RESULT = 4

        # Estado transitorio para recetas (flujo: load → cleansing → cross).
        self._pending_recipe: Recipe | None = None
        # Reglas de limpieza actualmente aplicadas (para incluir en receta).
        self._active_cleansing_rules: list[CleansingRule] = []

        # Conexion de senales entre pantallas.
        self._load_screen.files_confirmed.connect(self._on_files_confirmed)
        self._load_screen.recipe_applied.connect(self._on_recipe_applied)

        self._cleansing_screen.cleansing_completed.connect(self._on_cleansing_completed)
        self._cleansing_screen.skip_requested.connect(self._on_cleansing_completed)
        self._cleansing_screen.back_requested.connect(self._go_to_load)

        self._cross_screen.cross_completed.connect(self._on_cross_completed)
        # Al presionar "Volver" en el cruce, volvemos a limpieza (no a carga).
        # Esto permite ajustar reglas sin recargar archivos.
        self._cross_screen.back_requested.connect(self._go_to_clean)
        self._cross_screen.save_recipe_requested.connect(self._on_save_recipe_requested)

        self._rules_screen.rules_completed.connect(self._on_rules_completed)
        self._rules_screen.skip_requested.connect(self._on_rules_completed)
        self._rules_screen.back_requested.connect(self._go_to_cross)

        self._result_screen.new_cross_requested.connect(self._on_new_cross)
        self._result_screen.back_to_config_requested.connect(self._go_to_rules)
        self._result_screen.use_as_base_requested.connect(self._on_use_as_base)

        # Barra de estado.
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._lbl_user = QLabel()
        self._lbl_timer = QLabel()
        self._status_bar.addWidget(self._lbl_user)
        self._status_bar.addPermanentWidget(self._lbl_timer)

        # Timer de inactividad (verifica cada 30 segundos).
        self._inactivity_timer = QTimer(self)
        self._inactivity_timer.setInterval(30_000)
        self._inactivity_timer.timeout.connect(self._check_session_timeout)
        self._inactivity_timer.start()

        # Timer de actualizacion de la barra de estado (cada 60 segundos).
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(60_000)
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start()

    # ------------------------------------------------------------------
    # Sesion
    # ------------------------------------------------------------------

    def on_login(self, user: User) -> None:
        """Llamado desde LoginScreen cuando el login es exitoso."""
        self._lbl_user.setText(f"Usuario: {user.username}")
        self._update_status_bar()
        # Propagar el usuario activo a LoadScreen para que los logs de auditoria
        # tengan trazabilidad correcta (DEF-002).
        self._load_screen.set_username(user.username)
        self._go_to_load()
        self.show()
        # Refrescar actividad en todas las interacciones con la ventana.
        self.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        """Refresca el timeout de inactividad en cualquier interaccion."""
        self._session.refresh_activity()
        return super().eventFilter(obj, event)

    def _check_session_timeout(self) -> None:
        if self._session.is_expired() and self._session.current_user() is not None:
            user = self._session.current_user()
            username = user.username if user else ""
            self._logger.log(AuditEntry(
                timestamp=make_timestamp(),
                usuario=username,
                accion="LOGOUT",
                extra={"motivo": "timeout_inactividad"},
            ))
            self._session.end()
            QMessageBox.information(
                self,
                "Sesion expirada",
                "La sesion expiro por inactividad. Volvera a la pantalla de login.",
            )
            self.hide()
            self._request_login()

    def _request_login(self) -> None:
        """Emite senal para que main.py reabra el dialogo de login."""
        # Usamos una senal informal a traves del parent o directamente llamamos al cierre.
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()  # Simplificado: cierra la app; main.py puede relanzar.

    def _update_status_bar(self) -> None:
        user = self._session.current_user()
        if user:
            self._lbl_user.setText(f"Usuario: {user.username}")

    # ------------------------------------------------------------------
    # Navegacion
    # ------------------------------------------------------------------

    def _go_to_load(self) -> None:
        self._stack.setCurrentIndex(IDX_LOAD)

    def _go_to_clean(self) -> None:
        self._stack.setCurrentIndex(IDX_CLEAN)

    def _go_to_cross(self) -> None:
        self._stack.setCurrentIndex(IDX_CROSS)

    def _go_to_rules(self) -> None:
        self._stack.setCurrentIndex(IDX_RULES)

    def _go_to_result(self) -> None:
        self._stack.setCurrentIndex(IDX_RESULT)

    def _on_files_confirmed(self, file_entries: list[FileEntry]) -> None:
        """Archivos validados; pasar a la pantalla de limpieza."""
        user = self._session.current_user()
        username = user.username if user else ""
        self._cleansing_screen.load_files(file_entries, current_user=username)
        self._go_to_clean()

    def _on_cleansing_completed(self, file_entries: list[FileEntry]) -> None:
        """Limpieza aplicada (o saltada); pasar a configuracion del cruce."""
        user = self._session.current_user()
        username = user.username if user else ""
        self._cross_screen.load_files(file_entries, current_user=username)

        # Capturar las reglas actualmente visibles en la pantalla de limpieza
        # para poder incluirlas en una receta que se guarde desde el cruce.
        active_rules = [row.get_rule() for row in self._cleansing_screen._rule_rows]
        self._active_cleansing_rules = active_rules
        self._cross_screen.set_cleansing_rules(active_rules)

        if self._pending_recipe:
            self._cross_screen.load_recipe_config(self._pending_recipe, file_entries)
            self._pending_recipe = None

        self._go_to_cross()

    def _on_recipe_applied(self, recipe: Recipe, file_entries: list[FileEntry]) -> None:
        """
        Flujo receta: pre-llenar limpieza y cruce, luego navegar.
        1. Inicializa CleansingScreen con los archivos cargados.
        2. Carga las reglas de la receta en CleansingScreen.
        3. Guarda la receta pendiente para pre-cargar CrossScreen al continuar.
        """
        user = self._session.current_user()
        username = user.username if user else ""
        self._cleansing_screen.load_files(file_entries, current_user=username)
        self._cleansing_screen.load_recipe_rules(recipe.cleansing_rules)
        self._pending_recipe = recipe
        self._go_to_clean()

    def _on_save_recipe_requested(
        self,
        file_entries: list[FileEntry],
        cleansing_rules: list[CleansingRule],
        cross_steps: list,
        join_type: str,
        normalize_keys: bool,
    ) -> None:
        """Abre SaveRecipeDialog con el estado actual del cruce."""
        from config import config
        from ui.recipe_dialog import SaveRecipeDialog

        user = self._session.current_user()
        username = user.username if user else ""

        dlg = SaveRecipeDialog(
            file_entries=file_entries,
            cleansing_rules=cleansing_rules,
            cross_steps=cross_steps,
            join_type=join_type,
            normalize_keys=normalize_keys,
            recipes_dir=config.recipes_dir,
            audit_logger=self._logger,
            current_user=username,
            parent=self,
        )
        dlg.exec()

    def _on_cross_completed(self, result: CrossResult) -> None:
        """Cruce finalizado; pasar a la pantalla de reglas de negocio."""
        user = self._session.current_user()
        username = user.username if user else ""
        self._rules_screen.load_result(result, current_user=username)
        self._go_to_rules()

    def _on_rules_completed(self, result: CrossResult) -> None:
        """Reglas aplicadas (o saltadas); mostrar resultado."""
        user = self._session.current_user()
        username = user.username if user else ""
        self._result_screen.show_result(result, current_user=username)
        self._go_to_result()

    def _on_new_cross(self) -> None:
        """Iniciar un cruce nuevo con estado limpio."""
        self._load_screen.reset()
        self._go_to_load()

    def _on_use_as_base(self, result: CrossResult) -> None:
        """
        Cruce secuencial: toma el resultado actual como archivo virtual
        y vuelve a la pantalla de carga para agregar más archivos.
        """
        user = self._session.current_user()
        username = user.username if user else ""
        self._load_screen.reset()
        self._load_screen.set_username(username)
        self._load_screen.preload_result(result, label="Resultado previo")
        self._go_to_load()

    def closeEvent(self, event) -> None:
        """Registrar LOGOUT al cerrar la ventana y asegurar que la app termine."""
        user = self._session.current_user()
        if user:
            self._logger.log(AuditEntry(
                timestamp=make_timestamp(),
                usuario=user.username,
                accion="LOGOUT",
                extra={"motivo": "cierre_voluntario"},
            ))
            self._session.end()
        event.accept()
        QApplication.instance().quit()
