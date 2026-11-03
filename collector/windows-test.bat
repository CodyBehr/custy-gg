@echo off
rem Checks that config.json is right, the site is reachable and League is found.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 custy_collector.py --test & goto :end)
where python >nul 2>nul && (python custy_collector.py --test & goto :end)
echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
:end
pause
