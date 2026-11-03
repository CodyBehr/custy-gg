@echo off
rem Stops the collector from starting with Windows and stops the running copy.
set "VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\custy-collector.vbs"
if exist "%VBS%" del "%VBS%"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*custy_collector.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Autostart removed and collector stopped.
pause
