#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Виртуальное окружение не найдено."
  echo "Сначала выполните ./setup.sh"
  exit 1
fi

source .venv/bin/activate
exec python main.py
