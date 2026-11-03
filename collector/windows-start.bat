@echo off
rem Runs the collector in this window. Close the window to stop it.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 custy_collector.py %* & goto :end)
where python >nul 2>nul && (python custy_collector.py %* & goto :end)
echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
:end
pause
