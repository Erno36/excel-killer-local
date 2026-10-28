"""
scripts/create_user.py — Administracion de usuarios desde consola (HU-08, D-06).

Uso:
    python scripts/create_user.py create <username> <password>
    python scripts/create_user.py deactivate <username>
    python scripts/create_user.py activate <username>
    python scripts/create_user.py reset <username> <new_password>

Variables de entorno requeridas: DB_PATH (o valor por defecto cruzador.db).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth.service import UserManager
from config import config
from data.db import init_db


def usage() -> None:
    print(
        "Uso:\n"
        "  create_user.py create <username> <password>\n"
        "  create_user.py deactivate <username>\n"
        "  create_user.py activate <username>\n"
        "  create_user.py reset <username> <new_password>\n"
    )
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 3:
        usage()

    command = sys.argv[1]
    conn = init_db(config.db_path, is_development=config.is_development)
    mgr = UserManager(conn)

    try:
        if command == "create":
            if len(sys.argv) < 4:
                usage()
            username, password = sys.argv[2], sys.argv[3]
            user = mgr.create_user(username, password)
            print(f"Usuario '{user.username}' creado (id={user.id}).")

        elif command == "deactivate":
            username = sys.argv[2]
            mgr.deactivate_user(username)
            print(f"Usuario '{username}' desactivado.")

        elif command == "activate":
            username = sys.argv[2]
            mgr.activate_user(username)
            print(f"Usuario '{username}' activado.")

        elif command == "reset":
            if len(sys.argv) < 4:
                usage()
            username, new_password = sys.argv[2], sys.argv[3]
            mgr.reset_password(username, new_password)
            print(f"Contrasena de '{username}' actualizada.")

        else:
            usage()

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
