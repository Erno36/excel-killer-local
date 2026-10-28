"""
main.py — Punto de entrada de la aplicacion Cruzador Excel.

Banco Piano — Gerencia Comercial de Consumo.

Flujo:
1. Carga configuracion desde .env.
2. Inicializa base SQLite y aplica migraciones.
3. Inicializa el logger de auditoria.
4. Muestra el dialogo de login.
5. Si el login es exitoso, abre la ventana principal.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Agregar el directorio raiz al path para que los imports funcionen
# independientemente del directorio de trabajo.
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox

from auth.service import AuthService, SessionManager
from audit.logger import setup_logger
from config import config
from data.db import init_db
from ui.login_screen import LoginScreen
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Cruzador Excel")
    app.setOrganizationName("Banco Piano")

    # Estilo global: fondo blanco, texto negro, botones azules.
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QWidget {
            background-color: #ffffff;
            color: #000000;
            font-family: "Segoe UI", Arial, sans-serif;
            font-size: 13px;
        }
        QDialog {
            background-color: #ffffff;
        }
        QMainWindow {
            background-color: #ffffff;
        }
        QLabel {
            background-color: transparent;
            color: #000000;
        }
        QPushButton {
            background-color: #1a5fa8;
            color: #ffffff;
            border: none;
            border-radius: 4px;
            padding: 6px 16px;
            font-weight: bold;
            min-height: 28px;
        }
        QPushButton:hover {
            background-color: #154f8e;
        }
        QPushButton:pressed {
            background-color: #0d3d6e;
        }
        QPushButton:disabled {
            background-color: #9fb8d4;
            color: #ffffff;
        }
        QLineEdit {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #aaaaaa;
            border-radius: 4px;
            padding: 4px 8px;
        }
        QLineEdit:focus {
            border: 1.5px solid #1a5fa8;
        }
        QComboBox {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #aaaaaa;
            border-radius: 4px;
            padding: 4px 8px;
        }
        QComboBox:focus {
            border: 1.5px solid #1a5fa8;
        }
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #000000;
            selection-background-color: #1a5fa8;
            selection-color: #ffffff;
        }
        QTableView {
            background-color: #ffffff;
            color: #000000;
            gridline-color: #dddddd;
            border: 1px solid #dddddd;
        }
        QTableView::item:selected {
            background-color: #1a5fa8;
            color: #ffffff;
        }
        QHeaderView::section {
            background-color: #f0f4f9;
            color: #000000;
            border: 1px solid #dddddd;
            padding: 4px 8px;
            font-weight: bold;
        }
        QScrollArea {
            background-color: #ffffff;
            border: none;
        }
        QScrollBar:vertical {
            background-color: #f0f0f0;
            width: 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background-color: #aaaaaa;
            border-radius: 6px;
            min-height: 20px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        QTabWidget::pane {
            background-color: #ffffff;
            border: 1px solid #dddddd;
        }
        QTabBar::tab {
            background-color: #f0f4f9;
            color: #000000;
            padding: 6px 16px;
            border: 1px solid #dddddd;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #ffffff;
            color: #1a5fa8;
            font-weight: bold;
            border-bottom: 2px solid #1a5fa8;
        }
        QFrame {
            background-color: transparent;
        }
        QMessageBox {
            background-color: #ffffff;
        }
        QToolTip {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #aaaaaa;
        }
    """)

    # Inicializar logger de auditoria.
    audit_logger = setup_logger(config.log_dir)

    # Inicializar base de datos.
    try:
        conn = init_db(config.db_path, is_development=config.is_development)
    except Exception as exc:
        QMessageBox.critical(
            None,
            "Error de inicializacion",
            f"No se pudo inicializar la base de datos.\n\n{exc}",
        )
        return 1

    # Servicios de autenticacion.
    auth_service = AuthService(
        conn=conn,
        max_attempts=config.login_max_attempts,
        lockout_minutes=config.login_lockout_minutes,
    )
    session_manager = SessionManager(timeout_minutes=config.session_timeout_minutes)

    # Ventana principal (se muestra solo tras login exitoso).
    main_window = MainWindow(
        session_manager=session_manager,
        audit_logger=audit_logger,
    )

    # Dialogo de login.
    login_screen = LoginScreen(
        auth_service=auth_service,
        session_manager=session_manager,
        audit_logger=audit_logger,
    )
    login_screen.login_successful.connect(main_window.on_login)

    # Bucle: mostrar login hasta que sea exitoso o el usuario cierre.
    result = login_screen.exec()
    if result != LoginScreen.DialogCode.Accepted:
        return 0

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
