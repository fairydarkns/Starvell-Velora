@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Виртуальное окружение не найдено.
    echo Сначала запустите Setup.bat
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Не удалось активировать виртуальное окружение.
    pause
    exit /b 1
)

python main.py
pause
