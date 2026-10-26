@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===============================================
echo  Drill D1-D3 + Vision console
echo  (force plot window will open automatically)
echo ===============================================
start "" /b pythonw "%~dp0tools\drill_plot\force_plot.py" --watch "%~dp0runtime\motion_logs"
python code\pc\drill_console.py
echo.
pause
