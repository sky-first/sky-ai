#!/bin/bash

# Script para rodar o worker do Celery do AI
# Uso: ./scripts/start-ai-worker.sh

set -e

AI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "👷 Starting AI Celery Worker..."

cd "$AI_DIR"

# Check if virtual environment exists
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    echo "⚠️  Virtual environment not found. Creating..."
    python3 -m venv venv
fi

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Configure environment variables
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://localhost:6379/0}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://localhost:6379/0}"

echo "✅ Environment variables configured"
echo "   CELERY_BROKER_URL: $CELERY_BROKER_URL"
echo ""

# Run worker
echo "🔄 Starting Celery worker..."
if [ -d "venv" ]; then
    venv/bin/celery -A worker.celery_app worker --loglevel=info --concurrency=4
elif [ -d ".venv" ]; then
    .venv/bin/celery -A worker.celery_app worker --loglevel=info --concurrency=4
else
    celery -A worker.celery_app worker --loglevel=info --concurrency=4
fi

