@echo off
REM scripts/get_my_ip_cmd.bat
REM Script batch para descobrir IP público (não requer PowerShell)

echo Descobrindo seu IP publico...
echo.

REM Tentar com PowerShell se disponível
powershell -Command "(Invoke-WebRequest -Uri 'https://api.ipify.org' -UseBasicParsing).Content" 2>nul

if errorlevel 1 (
    echo.
    echo Erro: PowerShell nao disponivel ou falhou
    echo.
    echo Tente manualmente:
    echo   1. Abra: https://api.ipify.org no navegador
    echo   2. Ou use: curl https://api.ipify.org
    echo.
    pause
)

