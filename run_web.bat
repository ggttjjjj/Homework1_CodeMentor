@echo off
rem CodeMentor Web launcher.
rem First run: extracts the bundled source archive, then starts the web UI.
rem Browser opens automatically at http://127.0.0.1:8000
cd /d "%~dp0"

if not exist "web\index.html" (
    echo Extracting source files, first run only...
    tar -xf CodeMentor-source.zip 2>nul || powershell -NoProfile -Command "Expand-Archive -Path 'CodeMentor-source.zip' -DestinationPath '.' -Force"
    if not exist "web.py" (
        echo.
        echo [FAILED] Source extraction failed. Please extract CodeMentor-source.zip manually.
        pause
        exit /b 1
    )
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 web.py %*
) else (
    python web.py %*
)

if %errorlevel% neq 0 (
    echo.
    echo [FAILED] Copy the error message above for feedback.
    echo Hints: missing "flask" = run:  pip install -r requirements.txt
    echo       no API key = the setup wizard will guide you on first open
    echo       offline demo:  py -3 web.py --mock
    pause
)
