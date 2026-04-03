#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "========================================"
echo "        StarvellVelora Setup"
echo "========================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 не найден."
  echo "Установите python3 и python3-venv, затем повторите запуск."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Создаю виртуальное окружение..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "Обновляю pip..."
python -m pip install --upgrade pip

echo "Устанавливаю зависимости..."
python -m pip install -r requirements.txt

echo
echo "Установка завершена."
echo "Для запуска используйте ./start.sh"
