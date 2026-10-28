"""
config.py — Lectura de variables de entorno y configuracion global.

Carga el archivo .env si existe. Expone AppConfig como dataclass.
Ningun secreto se escribe aqui; todo viene de variables de entorno o .env.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Directorio raiz del proyecto (carpeta que contiene main.py y config.py).
_BASE_DIR: Path = Path(__file__).parent

from dotenv import load_dotenv

# Carga .env del directorio de trabajo si existe (no falla si no existe).
load_dotenv(override=False)


@dataclass(frozen=True)
class AppConfig:
    app_env: str
    db_path: Path
    log_dir: Path
    session_timeout_minutes: int
    login_max_attempts: int
    login_lockout_minutes: int

    @property
    def base_dir(self) -> Path:
        """Directorio raiz del proyecto (donde vive main.py)."""
        return _BASE_DIR

    @property
    def recipes_dir(self) -> Path:
        """Directorio de recetas reutilizables."""
        return _BASE_DIR / "recipes"

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


def load_config() -> AppConfig:
    """Lee variables de entorno y devuelve AppConfig."""
    app_env = os.getenv("APP_ENV", "development").strip()
    if os.name == "nt":
        app_data_dir = Path(
            os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        ) / "BancoPiano" / "CruzadorExcel"
    elif sys.platform == "darwin":
        app_data_dir = Path.home() / "Library" / "Application Support" / "BancoPiano" / "CruzadorExcel"
    else:
        app_data_dir = Path(
            os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")
        ) / "banco-piano" / "cruzador-excel"

    db_path = Path(os.getenv("DB_PATH", app_data_dir / "cruzador.db"))
    log_dir = Path(os.getenv("LOG_DIR", app_data_dir / "logs"))
    session_timeout = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))
    login_max_attempts = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
    login_lockout_minutes = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "5"))

    return AppConfig(
        app_env=app_env,
        db_path=db_path,
        log_dir=log_dir,
        session_timeout_minutes=session_timeout,
        login_max_attempts=login_max_attempts,
        login_lockout_minutes=login_lockout_minutes,
    )


# Instancia global — se crea una vez al importar el modulo.
config: AppConfig = load_config()
