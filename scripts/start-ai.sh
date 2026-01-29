#!/bin/bash

# Script to run AI Service with uvicorn
# Usage: ./scripts/start-ai.sh

set -e

AI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🤖 Starting AI Service on port 8001..."

cd "$AI_DIR"

# Check if regular virtual environment exists
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    echo "⚠️  Virtual environment not found. Creating..."
    python3 -m venv venv
    # Clear dependencies marker to force re-install
    rm -f .deps_installed
fi

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Check if requirements.txt has changed since last install
if [ -f "requirements.txt" ] && [ -f ".deps_installed" ]; then
    if [ "requirements.txt" -nt ".deps_installed" ]; then
        echo "🔄 Requirements updated. Triggering re-install..."
        rm -f .deps_installed
    fi
fi

# Install dependencies if needed
if [ ! -f ".deps_installed" ]; then
    echo "📦 Installing dependencies..."
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

# Configure environment variables
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://localhost:6379/0}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://localhost:6379/0}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-}"

echo "✅ Environment variables configured"
echo "   DATABASE_URL: $DATABASE_URL"
echo "   CELERY_BROKER_URL: $CELERY_BROKER_URL"
echo ""

# Check if infrastructure is running
if ! docker ps | grep -q sky_poc_postgres; then
    echo "⚠️  Infrastructure is not running."
    echo "   Run: cd ../../deploy && ./start.sh"
    echo "   Continuing..."
fi

# Run uvicorn
echo "🌐 Starting server on port 8001..."
if [ -d "venv" ]; then
    venv/bin/python run_api.py
elif [ -d ".venv" ]; then
    .venv/bin/python run_api.py
else
    python3 run_api.py
fi
