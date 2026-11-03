@echo off
rem Starts the collector hidden every time you log in to Windows, and starts it now.
setlocal
cd /d "%~dp0"
set "SCRIPT=%~dp0custy_collector.py"
set "PYW="
for /f "delims=" %%i in ('where pyw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
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
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS=%STARTUP%\custy-collector.vbs"
> "%VBS%" echo CreateObject("WScript.Shell").Run """%PYW%"" ""%SCRIPT%""", 0, False
start "" wscript "%VBS%"
echo Done. The collector now runs in the background whenever you log in to Windows.
echo Activity is written to collector.log in this folder.
pause
