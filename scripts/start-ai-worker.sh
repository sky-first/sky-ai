#!/bin/bash

# Script para rodar o worker do Celery do AI
# Uso: ./scripts/start-ai-worker.sh

set -e

AI_DIR="/Users/thedatafirst/Desktop/Repositorios/sky-poc-ai"

echo "👷 Iniciando AI Celery Worker..."

cd "$AI_DIR"

# Verifica se o ambiente virtual existe
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    echo "⚠️  Ambiente virtual não encontrado. Criando..."
    python3 -m venv venv
fi

# Ativa o ambiente virtual
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Configura variáveis de ambiente
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://localhost:6379/0}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://localhost:6379/0}"

echo "✅ Variáveis de ambiente configuradas"
echo "   CELERY_BROKER_URL: $CELERY_BROKER_URL"
echo ""

# Roda o worker
echo "🔄 Iniciando Celery worker..."
if [ -d "venv" ]; then
    venv/bin/celery -A worker.celery_app worker --loglevel=info --concurrency=4
elif [ -d ".venv" ]; then
    .venv/bin/celery -A worker.celery_app worker --loglevel=info --concurrency=4
else
    celery -A worker.celery_app worker --loglevel=info --concurrency=4
fi

