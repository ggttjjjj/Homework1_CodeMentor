@echo off
rem CodeMentor CLI launcher.
rem First run: extracts the bundled source archive, then starts the CLI.
cd /d "%~dp0"

if not exist "web\index.html" (
    echo Extracting source files, first run only...
    tar -xf CodeMentor-source.zip 2>nul || powershell -NoProfile -Command "Expand-Archive -Path 'CodeMentor-source.zip' -DestinationPath '.' -Force"
    if not exist "main.py" (
        echo.
        echo [FAILED] Source extraction failed. Please extract CodeMentor-source.zip manually.
        pause
        exit /b 1
    )
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 main.py %*
) else (
    python main.py %*
)

if %errorlevel% neq 0 (
    echo.
    echo [FAILED] Copy the error message above for feedback.
    echo Hints: missing "requests" = run:  pip install -r requirements.txt
    echo       no API key configured = copy .env.example to .env and fill it,
    echo       or try offline demo:  py -3 main.py --provider mock
    echo       web UI: run_web.bat
    pause
)
