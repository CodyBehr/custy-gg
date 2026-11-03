@echo off
rem Starts the collector hidden every time you log in to Windows, and starts it now.
setlocal
cd /d "%~dp0"
set "SCRIPT=%~dp0custy_collector.py"

rem Find the windowless Python (pythonw), so no console window stays open.
set "PYW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW for /f "delims=" %%i in ('where pyw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist "%~dp0config.json" (
  echo config.json is missing. Copy config.example.json to config.json and fill it in first.
  pause
  exit /b 1
)

rem Ask Windows where this user's Startup folder is (it can be moved, e.g. by OneDrive), and create it if needed.
set "STARTUP="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Startup')"`) do set "STARTUP=%%i"
if not defined STARTUP set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%STARTUP%" mkdir "%STARTUP%"

set "VBS=%STARTUP%\custy-collector.vbs"
> "%VBS%" echo CreateObject("WScript.Shell").Run """%PYW%"" ""%SCRIPT%""", 0, False
if not exist "%VBS%" (
  echo Could not create the startup file in:
  echo   %STARTUP%
  echo Run windows-start.bat instead to keep the collector running in a window.
  pause
  exit /b 1
)

rem Stop any copy that's already running, then start one hidden.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*custy_collector.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul
start "" wscript "%VBS%"

echo Done. The collector is running in the background and will start again whenever you log in to Windows.
echo You can close this window. Activity is written to collector.log in this folder.
pause
