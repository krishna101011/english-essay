@echo off
setlocal

rem One-time project setup: create the venv, install dependencies, apply
rem database migrations. Safe to re-run - it skips venv creation if one
rem already exists and reinstalls/upgrades requirements either way.

where java >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Java was not found on your PATH.
    echo The local grammar checker ^(LanguageTool^) requires a JDK 17+ runtime.
    echo Install one from https://adoptium.net/ and then re-run setup.bat.
    echo.
    exit /b 1
)

if not exist ".env" (
    echo.
    echo ERROR: .env not found.
    echo Copy .env.example to .env and fill in real values for
    echo SESSION_SECRET_KEY and ENCRYPTION_KEY before running setup.bat.
    echo   copy .env.example .env
    echo.
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment in .\venv ...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment. Is Python 3.11+ installed and on PATH?
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo Installing dependencies from requirements.txt ...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. See the output above.
    exit /b 1
)

echo Applying database migrations ...
alembic upgrade head
if errorlevel 1 (
    echo ERROR: alembic upgrade head failed. See the output above.
    exit /b 1
)

echo.
echo Setup complete. Run start.bat to launch the app.
