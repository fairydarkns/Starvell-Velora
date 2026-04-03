@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo         StarvellVelora Setup
echo ========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=py -3"
) else (
    set "PY_CMD=python"
)

%PY_CMD% --version >nul 2>nul
if errorlevel 1 (
    echo Python 3 не найден.
    echo Установите Python 3.11 или новее и повторите попытку.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo Не удалось создать виртуальное окружение.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Не удалось активировать виртуальное окружение.
    pause
    exit /b 1
)

echo Обновляю pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo Не удалось обновить pip.
    pause
    exit /b 1
)

echo Устанавливаю зависимости...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Не удалось установить зависимости.
    pause
    exit /b 1
)

echo.
echo Установка завершена.
echo Для запуска используйте Start.bat
pause
