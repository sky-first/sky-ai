#!/bin/bash

set -e

cd ~/projeto/poc-deploy
CONTAINER_NAME="ai_saas_postgres_prod"
DB_USER="postgres"
DB_NAME="ai_saas_db"

echo "Instalando pgvector no banco: $DB_NAME"

if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "ERRO: Container não está rodando!"
    exit 1
fi

ACTUAL_DB=$(docker exec $CONTAINER_NAME sh -c "echo \$POSTGRES_DB" 2>/dev/null || echo "ai_saas_db")
if [ "$ACTUAL_DB" != "$DB_NAME" ]; then
    echo "AVISO: Banco configurado ($ACTUAL_DB) diferente do esperado ($DB_NAME)"
    DB_NAME="$ACTUAL_DB"
fi

DB_EXISTS=$(docker exec $CONTAINER_NAME psql -U $DB_USER -lqt 2>/dev/null | cut -d \| -f 1 | grep -w "$DB_NAME" | wc -l | tr -d ' ' || echo "0")
if [ "$DB_EXISTS" -eq 0 ]; then
    echo "ERRO: Banco $DB_NAME não existe!"
    docker exec $CONTAINER_NAME psql -U $DB_USER -l 2>/dev/null || true
    exit 1
fi

VECTOR_FILES=$(docker exec $CONTAINER_NAME sh -c "find /usr -name 'vector.control' 2>/dev/null | wc -l" | tr -d ' ' || echo "0")
if [ "$VECTOR_FILES" -eq 0 ]; then
    echo "Instalando pgvector no sistema..."
    docker exec $CONTAINER_NAME sh -c "apk update && apk add --no-cache git build-base postgresql-dev" 2>&1
    
    docker exec $CONTAINER_NAME sh -c "
        cd /tmp && \
        rm -rf pgvector && \
        git clone --branch v0.5.0 https://github.com/pgvector/pgvector.git && \
        cd pgvector && \
        make USE_PGXS=1 2>&1 | grep -v 'clang-19' | grep -v 'Error 127' || true && \
        if [ -f vector.so ]; then
            mkdir -p /usr/local/lib/postgresql
            mkdir -p /usr/local/share/postgresql/extension
            cp vector.so /usr/local/lib/postgresql/vector.so
            cp sql/*.sql /usr/local/share/postgresql/extension/
            cp vector.control /usr/local/share/postgresql/extension/
            echo 'pgvector instalado'
        else
            echo 'Erro: vector.so não foi criado'
            exit 1
        fi && \
        cd / && \
        rm -rf /tmp/pgvector
    " 2>&1
    
    docker restart $CONTAINER_NAME
    sleep 8
fi

sleep 3
AVAILABLE=$(docker exec $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -t -c "SELECT COUNT(*) FROM pg_available_extensions WHERE name = 'vector';" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$AVAILABLE" -eq 0 ]; then
    echo "ERRO: pgvector não está disponível"
    exit 1
fi

INSTALLED=$(docker exec $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -t -c "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector';" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$INSTALLED" -eq 0 ]; then
    docker exec $CONTAINER_NAME psql -U $DB_USER -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERRO: Falha ao criar extensão"
        exit 1
    fi
fi

FINAL_CHECK=$(docker exec $CONTAINER_NAME psql -U $DB_USER -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector';" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$FINAL_CHECK" -gt 0 ]; then
    echo "SUCESSO: Extensão vector instalada no banco $DB_NAME"
    docker exec $CONTAINER_NAME psql -U $DB_USER -d "$DB_NAME" -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';" 2>/dev/null
else
    echo "ERRO: Extensão não foi criada"
    exit 1
fi
