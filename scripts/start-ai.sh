#!/bin/bash

# Script para rodar o AI Service com uvicorn
# Uso: ./scripts/start-ai.sh

set -e

AI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🤖 Iniciando AI Service na porta 8001..."

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

# Instala dependências se necessário
if [ ! -f ".deps_installed" ]; then
    echo "📦 Instalando dependências..."
    if [ -d "venv" ]; then
        venv/bin/pip install -q --upgrade pip
        venv/bin/pip install -q psycopg2-binary || venv/bin/pip install -q "psycopg2-binary>=2.9.0" || true
        grep -v "psycopg2-binary==" requirements.txt > /tmp/requirements_ai_temp.txt || cp requirements.txt /tmp/requirements_ai_temp.txt
        venv/bin/pip install -q -r /tmp/requirements_ai_temp.txt || true
        rm -f /tmp/requirements_ai_temp.txt
    elif [ -d ".venv" ]; then
        .venv/bin/pip install -q --upgrade pip
        .venv/bin/pip install -q psycopg2-binary || .venv/bin/pip install -q "psycopg2-binary>=2.9.0" || true
        grep -v "psycopg2-binary==" requirements.txt > /tmp/requirements_ai_temp.txt || cp requirements.txt /tmp/requirements_ai_temp.txt
        .venv/bin/pip install -q -r /tmp/requirements_ai_temp.txt || true
        rm -f /tmp/requirements_ai_temp.txt
    else
        pip install -q --upgrade pip
        pip install -q psycopg2-binary || pip install -q "psycopg2-binary>=2.9.0" || true
        grep -v "psycopg2-binary==" requirements.txt > /tmp/requirements_ai_temp.txt || cp requirements.txt /tmp/requirements_ai_temp.txt
        pip install -q -r /tmp/requirements_ai_temp.txt || true
        rm -f /tmp/requirements_ai_temp.txt
    fi
    touch .deps_installed
fi

# Configura variáveis de ambiente
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://localhost:6379/0}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://localhost:6379/0}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"

echo "✅ Variáveis de ambiente configuradas"
echo "   DATABASE_URL: $DATABASE_URL"
echo "   CELERY_BROKER_URL: $CELERY_BROKER_URL"
echo ""

# Verifica se infraestrutura está rodando
if ! docker ps | grep -q sky_poc_postgres; then
    echo "⚠️  Infraestrutura não está rodando."
    echo "   Execute: cd ../../deploy && ./start.sh"
    echo "   Continuando..."
fi

# Roda o uvicorn
echo "🌐 Iniciando servidor na porta 8001..."
if [ -d "venv" ]; then
    venv/bin/python run_api.py
elif [ -d ".venv" ]; then
    .venv/bin/python run_api.py
else
    python3 run_api.py
fi
