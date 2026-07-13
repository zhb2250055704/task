@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  GM Tool - Diagnostic Mode
echo ============================================
echo.

set "PY_EXE=C:\Users\TU\AppData\Local\Programs\Python\Python310\python.exe"

echo [1] Checking Python...
if exist "%PY_EXE%" (
    echo     Found: %PY_EXE%
    "%PY_EXE%" --version
) else (
    echo     [ERROR] Python not found at %PY_EXE%
    goto :end
)
echo.

echo [2] Checking port 9092 usage...
netstat -ano | findstr :9092
if errorlevel 1 (
    echo     Port 9092 is FREE.
) else (
    echo     [WARN] Port 9092 is IN USE by the PID listed above.
    echo            Close that process, or the server cannot start.
)
echo.

echo [3] Starting server (errors will show below)...
echo --------------------------------------------
"%PY_EXE%" server.py
echo --------------------------------------------
echo Server exited with code = %ERRORLEVEL%

:end
echo.
pause
