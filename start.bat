@echo off
:: ============================================================
::  start.bat  ─  Start the LeetCode Discord Bot
::  Activates the local .venv and launches bot.py
:: ============================================================

setlocal

echo.
echo ====================================================
echo  LeetCode Discord Bot  ^|  Starting...
echo ====================================================
echo.

:: ── Verify .venv exists ──────────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] .venv not found. Please run setup.bat first.
    pause
    exit /b 1
)

:: ── Verify .env exists ───────────────────────────────────
if not exist ".env" (
    echo [ERROR] .env not found.
    echo         Copy .env.example to .env and fill in your credentials.
    pause
    exit /b 1
)

:: ── Activate venv ────────────────────────────────────────
call .venv\Scripts\activate.bat

:: ── Launch bot ───────────────────────────────────────────
echo [INFO]  Starting bot.py ...
echo [INFO]  Press Ctrl+C to stop.
echo.

python bot.py

:: ── Exit handling ────────────────────────────────────────
echo.
echo [INFO]  Bot has exited.
endlocal
pause
