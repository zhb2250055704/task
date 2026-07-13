@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  Cleaning up old servers on port 9092
echo ============================================
echo.

set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":9092" ^| findstr "LISTENING"') do (
    echo Killing PID %%P ...
    taskkill /F /PID %%P >nul 2>nul
    set "FOUND=1"
)

if "%FOUND%"=="0" (
    echo No listening process on port 9092. Already clean.
) else (
    echo Done. All old servers on port 9092 have been stopped.
)
echo.
echo Now you can run the start script again.
echo.
pause
