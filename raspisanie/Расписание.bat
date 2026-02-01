@echo off
chcp 65001 >nul
title Генератор расписания - Школа Покровский квартал

echo ============================================================
echo   Генератор расписания - Школа Покровский квартал
echo ============================================================
echo.

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден!
    echo Установите Python с https://python.org
    pause
    exit /b 1
)

REM Проверяем и устанавливаем зависимости
echo Проверка зависимостей...
pip show pywebview >nul 2>&1
if errorlevel 1 (
    echo Установка pywebview...
    pip install pywebview
)

pip show flask >nul 2>&1
if errorlevel 1 (
    echo Установка Flask...
    pip install flask flask-sqlalchemy
)

echo.
echo Запуск приложения...
echo.

cd /d "%~dp0"
python run_desktop.py

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось запустить приложение
    pause
)
