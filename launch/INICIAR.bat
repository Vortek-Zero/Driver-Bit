@echo off
REM WheelBridge — F5: checa tudo e inicia (duplo clique, sem terminal manual)
cd /d "%~dp0.."
set PY=launch\python-portatil\python.exe
if not exist "%PY%" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [FALHOU] Nenhum Python encontrado.
    echo Copie a pasta python-portatil para dentro de launch\ ^(ver PREPARAR.txt^)
    echo ou instale Python 3.10+ com "Add to PATH".
    pause
    exit /b 1
  )
  set PY=python
)
echo === 1/2 verificando hardware ===
"%PY%" check.py
if errorlevel 1 (
  echo.
  echo Corrija os itens [FALHOU] acima e rode de novo.
  pause
  exit /b 1
)
echo.
echo === 2/2 iniciando volante + dashboard ===
"%PY%" main.py --keyboard --browser
pause
