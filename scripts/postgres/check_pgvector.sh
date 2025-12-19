#!/bin/bash

set -e

CONTAINER_NAME="ai_saas_postgres_prod"
DB_USER="postgres"
DB_NAME="ai_saas_db"

echo "Verificando pgvector..."

if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "ERRO: Container não está rodando"
    exit 1
fi

IMAGE_NAME=$(docker inspect $CONTAINER_NAME --format='{{.Config.Image}}' 2>/dev/null || echo "não encontrada")
echo "Imagem: $IMAGE_NAME"

PG_VERSION=$(docker exec $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -t -c "SELECT version();" 2>/dev/null | head -1)
PG_MAJOR=$(echo "$PG_VERSION" | grep -oE "PostgreSQL [0-9]+" | grep -oE "[0-9]+" | head -1)
echo "PostgreSQL: $PG_MAJOR"

AVAILABLE=$(docker exec $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -t -c "SELECT * FROM pg_available_extensions WHERE name = 'vector';" 2>/dev/null | grep -c vector || echo "0")
if [ "$AVAILABLE" -gt 0 ]; then
    echo "pgvector disponível:"
    docker exec $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -c "SELECT name, default_version, installed_version FROM pg_available_extensions WHERE name = 'vector';" 2>/dev/null
else
    echo "ERRO: pgvector não está disponível"
    exit 1
fi

INSTALLED=$(docker exec $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -t -c "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector';" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$INSTALLED" -gt 0 ]; then
    echo "Extensão vector criada:"
    docker exec $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -c "SELECT extname, extversion, n.nspname FROM pg_extension e JOIN pg_namespace n ON e.extnamespace = n.oid WHERE extname = 'vector';" 2>/dev/null
else
    echo "AVISO: Extensão vector não foi criada"
    echo "Execute: docker exec $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -c 'CREATE EXTENSION IF NOT EXISTS vector;'"
fi
