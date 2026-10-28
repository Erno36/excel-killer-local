#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -x .venv/bin/python ]]; then
    PYTHON=.venv/bin/python
else
    PYTHON=python3
fi

"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --onefile \
    --windowed \
    --name CruzadorExcel-Linux \
    --add-data "$PWD/data/migrations:data/migrations" \
    --distpath ../../salidas/exes \
    --specpath build/linux \
    --workpath build/linux \
    main.py
