@echo off
chcp 65001 >nul

echo 🚀 Starting Claude to GCP proxy server...
echo 🚀 SSL_VERIFY disabled !!

set SSL_VERIFY=false

:: Check if Python is installed
where python >nul 2>&1
if %errorlevel% NEQ 0 (
    echo ❌ Error: Python not found. Please install Python first.
    exit /b 1
)

:: Check if service account file exists
if defined GCP_KEY_FILE (
    set KEY_FILE=%GCP_KEY_FILE%
) else (
    set KEY_FILE=key\key.json
)

if not exist "%KEY_FILE%" (
    echo ❌ Error: GCP service account file %KEY_FILE% not found.
    echo    Please place credentials at key\key.json or set GCP_KEY_FILE environment variable.
    exit /b 1
)

:: Check if requirements.txt exists
if not exist "requirements.txt" (
    echo ❌ Error: requirements.txt file not found.
    exit /b 1
)

:: Create and activate virtual environment
set VENV_DIR=.venv

if not exist "%VENV_DIR%" (
    echo 📦 Creating Python virtual environment...
    python -m venv %VENV_DIR%
    if %errorlevel% NEQ 0 (
        echo ❌ Failed to create virtual environment.
        exit /b 1
    )
)

echo 🔄 Activating virtual environment...
call %VENV_DIR%\Scripts\activate.bat

:: Check if dependencies need to be installed
set HASH_FILE=%VENV_DIR%\.requirements.hash
set NEED_INSTALL=0

:: Get current hash of requirements.txt
for /f "delims=" %%i in ('certutil -hashfile requirements.txt MD5 2^>nul ^| findstr /v ":" 2^>nul') do set CURRENT_HASH=%%i

:: Check if hash file exists and compare
if not exist "%HASH_FILE%" (
    set NEED_INSTALL=1
) else (
    set /p SAVED_HASH=<"%HASH_FILE%"
    if not "%CURRENT_HASH%"=="%SAVED_HASH%" set NEED_INSTALL=1
)

if %NEED_INSTALL%==1 (
    echo 📦 Installing Python dependencies...
    pip install -q -r requirements.txt
    if %errorlevel% NEQ 0 (
        echo ❌ Dependency installation failed. Please check the error messages.
        exit /b 1
    )
    echo %CURRENT_HASH%>"%HASH_FILE%"
    echo ✅ Dependencies installed successfully.
) else (
    echo ✅ Dependencies ready.
)
echo.
echo 🔧 Setting environment variable:
echo    set ANTHROPIC_BASE_URL=http://127.0.0.1:8000
set ANTHROPIC_BASE_URL=http://127.0.0.1:8000
echo.
echo 🌐 Proxy server will start at http://127.0.0.1:8000
echo 📋 Available endpoints:
echo    - GET  /health        - Health check
echo    - GET  /v1/models     - Get models list
echo    - POST /v1/messages   - Claude messages API
echo.
echo 🏃‍♂️ Starting server...

call python main.py