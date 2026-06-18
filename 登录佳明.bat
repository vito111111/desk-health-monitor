@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo   Garmin login  -  follow the prompts
echo ==========================================
python garmin_login.py
echo.
echo ---- press any key to close ----
pause >nul
