@echo off
setlocal

:: Script para rodar o AI Service no Windows CMD
:: Uso: scripts\start-ai.bat

echo 🤖 Iniciando AI Service no Windows...

:: Caminho para o diretório raiz do ai-service
set AI_DIR=%~dp0..
cd /d "%AI_DIR%"

:: Verifica se o ambiente virtual existe
if not exist "venv" (
    echo ⚠️  Ambiente virtual não encontrado. Criando...
    python -m venv venv
)

:: Ativa o ambiente virtual
call venv\Scripts\activate

:: Instala/Verifica dependências
echo 📦 Verificando dependências...
pip install -q -r requirements.txt

:: Configura variáveis de ambiente
if "%DATABASE_URL%"=="" set DATABASE_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/ai_saas_db
if "%CELERY_BROKER_URL%"=="" set CELERY_BROKER_URL=redis://localhost:6379/0
if "%CELERY_RESULT_BACKEND%"=="" set CELERY_RESULT_BACKEND=redis://localhost:6379/0
if "%OPENAI_API_KEY%"=="" set OPENAI_API_KEY=""

echo ✅ Variáveis de ambiente configuradas
echo    DATABASE_URL: %DATABASE_URL%
echo    CELERY_BROKER_URL: %CELERY_BROKER_URL%
echo.

:: Roda o servidor
echo 🌐 Iniciando servidor na porta 8001...
python run_api.py

pause
