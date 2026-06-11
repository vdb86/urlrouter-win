@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  URL Router - build script
echo ============================================================
echo.

REM ── Check Python ────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ and add it to PATH.
    pause & exit /b 1
)

REM ── Install / upgrade deps ──────────────────────────────────
echo [1/3]  Installing dependencies...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause & exit /b 1
)
echo.

REM ── Run PyInstaller ─────────────────────────────────────────
echo [2/3]  Building URLRouter.exe...
python -m PyInstaller URLRouter.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause & exit /b 1
)
echo.

REM ── Done ────────────────────────────────────────────────────
echo [3/3]  Done.
echo.
echo   Output: dist\URLRouter\URLRouter.exe
echo.
echo   The dist\URLRouter\ folder is fully self-contained and portable.
echo   Zip it, copy it anywhere, and run URLRouter.exe inside it.
echo   Config is stored as config.json next to URLRouter.exe.
echo.
pause
