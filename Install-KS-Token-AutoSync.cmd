@echo off
setlocal
set "EXT_DIR=%~dp0browser-extension\ks-token-auto-sync"

if not exist "%EXT_DIR%\manifest.json" (
  echo KS Token bridge files were not found.
  pause
  exit /b 1
)

start "" explorer.exe "%EXT_DIR%"

set "BROWSER_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

if defined BROWSER_EXE start "" "%BROWSER_EXE%" "chrome://extensions/"

echo.
echo Enable Developer mode, choose Load unpacked, and select:
echo %EXT_DIR%
echo.
pause
