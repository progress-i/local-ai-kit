#!/usr/bin/env bash
set -Eeuo pipefail
trap 'echo "ОШИБКА: строка $LINENO, код $?" >&2' ERR
KIT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
command -v python3 >/dev/null || { echo 'Требуется штатный python3 Ubuntu.' >&2; exit 1; }
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$KIT_DIR/app/bootstrap.py" "$@"
