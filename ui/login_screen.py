"""
ui/login_screen.py — Pantalla de login.

HU-01: autenticacion con usuario/contrasena.
Mensajes de error uniformes (CA-01-02, CA-01-03).
Sin stack traces en la UI (CA-07-03).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from audit.logger import AuditLogger, make_timestamp
from auth.service import AuthService, SessionManager
from data.models import AuditEntry, User

# ---------------------------------------------------------------------------
# Paleta de colores compartida (definida aqui como referencia central)
# ---------------------------------------------------------------------------
COLOR_PRIMARY      = "#1a3a6b"   # azul oscuro — titulos, botones principales
COLOR_PRIMARY_DARK = "#122a52"   # hover / borde activo
COLOR_PRIMARY_LIGHT = "#e8eef6"  # fondo de secciones secundarias
COLOR_TEXT_DARK    = "#1a1a2e"   # texto de cuerpo
COLOR_TEXT_MID     = "#444444"   # texto secundario
COLOR_ERROR        = "#c0392b"   # errores
COLOR_SUCCESS      = "#27ae60"   # exportar / acciones positivas
COLOR_WARNING      = "#e67e22"   # advertencias

STYLE_SCREEN_TITLE = (
    f"font-size: 18px; font-weight: bold; color: white; "
    f"background-color: {COLOR_PRIMARY}; "
    f"padding: 10px 16px; border-radius: 6px;"
)
STYLE_LABEL_FIELD = (
    f"font-size: 12px; font-weight: bold; color: {COLOR_PRIMARY};"
)
STYLE_BTN_PRIMARY = (
    f"background-color: {COLOR_PRIMARY}; color: white; "
    f"font-weight: bold; border-radius: 5px; padding: 6px 18px;"
)


class LoginScreen(QDialog):
    """
    Dialogo de login.
    Emite login_successful(User) cuando las credenciales son validas.
    """

    login_successful = Signal(object)  # User

    def __init__(
        self,
        auth_service: AuthService,
        session_manager: SessionManager,
        audit_logger: AuditLogger,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._auth = auth_service
        self._session = session_manager
        self._logger = audit_logger

        self.setWindowTitle("Banco Piano — Cruzador Excel")
        self.setMinimumWidth(400)
        self.setModal(True)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Banner superior azul ---
        banner = QFrame()
        banner.setStyleSheet(f"background-color: {COLOR_PRIMARY};")
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(32, 24, 32, 20)
        banner_layout.setSpacing(4)

        title = QLabel("Cruzador Excel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: white; background: transparent;"
        )
        banner_layout.addWidget(title)

        subtitle = QLabel("Banco Piano — Gerencia Comercial de Consumo")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size: 11px; color: #a8c4e0; background: transparent;")
        banner_layout.addWidget(subtitle)

        layout.addWidget(banner)

        # --- Formulario ---
        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: white;")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(36, 28, 36, 28)
        form_layout.setSpacing(10)

        lbl_user = QLabel("Usuario")
        lbl_user.setStyleSheet(STYLE_LABEL_FIELD)
        form_layout.addWidget(lbl_user)

        self._input_user = QLineEdit()
        self._input_user.setPlaceholderText("Ingrese su nombre de usuario")
        self._input_user.setMinimumHeight(38)
        self._input_user.setStyleSheet(
            f"border: 1.5px solid #ccd6e0; border-radius: 4px; "
            f"padding: 4px 10px; font-size: 13px; color: {COLOR_TEXT_DARK};"
        )
        form_layout.addWidget(self._input_user)

        form_layout.addSpacing(4)

        lbl_pass = QLabel("Contraseña")
        lbl_pass.setStyleSheet(STYLE_LABEL_FIELD)
        form_layout.addWidget(lbl_pass)

        self._input_pass = QLineEdit()
        self._input_pass.setPlaceholderText("Ingrese su contraseña")
        self._input_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._input_pass.setMinimumHeight(38)
        self._input_pass.setStyleSheet(
            f"border: 1.5px solid #ccd6e0; border-radius: 4px; "
            f"padding: 4px 10px; font-size: 13px; color: {COLOR_TEXT_DARK};"
        )
        form_layout.addWidget(self._input_pass)

        # Mensaje de error (oculto por defecto)
        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            f"color: {COLOR_ERROR}; font-size: 12px; "
            f"background-color: #fdecea; border-radius: 4px; padding: 6px 10px;"
        )
        self._error_label.hide()
        form_layout.addWidget(self._error_label)

        form_layout.addSpacing(6)

        # Boton ingresar
        self._btn_login = QPushButton("Ingresar")
        self._btn_login.setMinimumHeight(42)
        self._btn_login.setStyleSheet(
            f"background-color: {COLOR_PRIMARY}; color: white; "
            f"font-weight: bold; font-size: 14px; border-radius: 5px;"
            f"border: none;"
        )
        form_layout.addWidget(self._btn_login)

        layout.addWidget(form_frame)

        # Conectar senales
        self._btn_login.clicked.connect(self._on_login)
        self._input_pass.returnPressed.connect(self._on_login)
        self._input_user.returnPressed.connect(self._input_pass.setFocus)

    def _on_login(self) -> None:
        username = self._input_user.text().strip()
        password = self._input_pass.text()

        self._error_label.hide()

        if not username or not password:
            self._show_error("Ingrese usuario y contraseña.")
            return

        result = self._auth.authenticate(username, password)

        if result.success and result.user:
            self._logger.log(AuditEntry(
                timestamp=make_timestamp(),
                usuario=username,
                accion="LOGIN_OK",
            ))
            self._session.start(result.user)
            self._input_pass.clear()
            self.accept()
            self.login_successful.emit(result.user)
        else:
            self._logger.log(AuditEntry(
                timestamp=make_timestamp(),
                usuario=username,
                accion="LOGIN_FAIL",
                mensaje_error=result.message,
            ))
            self._input_pass.clear()
            self._show_error(result.message)

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()
