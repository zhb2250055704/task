@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting GM Command Tool...
echo.

echo Cleaning up old servers on port 9092...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":9092" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%P >nul 2>nul
)
echo Done.
echo.

set "PY_EXE=C:\Users\TU\AppData\Local\Programs\Python\Python310\python.exe"

if exist "%PY_EXE%" (
    "%PY_EXE%" server.py
    set "ERR=%ERRORLEVEL%"
    goto :end
)

where py >nul 2>nul && (
    py server.py
    set "ERR=%ERRORLEVEL%"
    goto :end
)

python --version >nul 2>nul && (
    python server.py
    set "ERR=%ERRORLEVEL%"
    goto :end
)

echo [ERROR] No usable Python interpreter found.
echo Please install Python from https://www.python.org/downloads/
set "ERR=9009"

:end
echo.
if not "%ERR%"=="0" (
    echo ============================================
    echo [INFO] Program exited with code = %ERR%
    echo If you see error 10048 above, the port is in use.
    echo Close other running windows, or run on another port:
    echo     "%PY_EXE%" server.py 9093
    echo ============================================
)
echo.
pause
