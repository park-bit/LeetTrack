@echo off
:: ============================================================
::  setup.bat  ─  One-time environment setup for LeetCode Bot
::  Creates a local .venv inside the project folder and
::  installs all dependencies.  No global installs, no admin.
:: ============================================================

setlocal enabledelayedexpansion

echo.
echo ====================================================
echo  LeetCode Discord Bot  ^|  Environment Setup
echo ====================================================
echo.

:: ── Check Python ─────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found in PATH.
    echo         Please install Python 3.11+ from https://python.org
    echo         and make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

for /f "tokens=2" %%V in ('python --version 2^>^&1') do set PY_VER=%%V
echo [INFO]  Found Python %PY_VER%

:: ── Create virtual environment ───────────────────────────
if exist ".venv" (
    echo [INFO]  .venv already exists — skipping creation.
) else (
    echo [INFO]  Creating virtual environment in .venv ...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK]    .venv created.
)

:: ── Activate venv ────────────────────────────────────────
call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate .venv.
    pause
    exit /b 1
)

:: ── Upgrade pip silently ─────────────────────────────────
echo [INFO]  Upgrading pip...
python -m pip install --upgrade pip --quiet
echo [OK]    pip upgraded.

:: ── Install dependencies ─────────────────────────────────
echo [INFO]  Installing dependencies from requirements.txt ...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)
echo [OK]    Dependencies installed.

:: ── Create .env if missing ───────────────────────────────
if not exist ".env" (
    copy .env.example .env >nul
    echo [OK]    Created .env from .env.example
    echo.
    echo [ACTION] Open .env and fill in:
    echo           DISCORD_TOKEN=your_bot_token
    echo           DISCORD_CHANNEL_ID=your_channel_id
) else (
    echo [INFO]  .env already exists — skipping copy.
)

:: ── Create required directories ──────────────────────────
if not exist "data"  mkdir data
if not exist "logs"  mkdir logs
echo [OK]    data/ and logs/ directories ready.

echo.
echo ====================================================
echo  Setup complete!
echo.
echo  Next steps:
echo    1. Edit .env with your Discord token + channel ID
echo    2. Edit profiles.json with your LeetCode users
echo    3. Run:  start.bat
echo ====================================================
echo.

endlocal
pause
