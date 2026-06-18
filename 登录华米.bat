@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo   Amazfit / Zepp Life login (China)
echo   need EMAIL + PASSWORD (not WeChat login)
echo ==========================================
python amazfit_login.py
echo.
echo ---- press any key to close ----
pause >nul
