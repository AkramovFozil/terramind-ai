@echo off
setlocal
cd /d "%~dp0"
if not exist "dist\index.html" (
  echo Xato: dist papkasi topilmadi. ZIP faylni to'liq oching.
  pause
  exit /b 1
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0serve-demo.py"
  goto :finish
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0serve-demo.py"
  goto :finish
)
echo Python 3 topilmadi. Python 3 o'rnatilgan kompyuterda ishga tushiring.
:finish
pause
