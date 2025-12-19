#!/bin/bash

CONTAINER_NAME="ai_saas_postgres_prod"

echo "=== Verificando container ==="
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "ERRO: Container '$CONTAINER_NAME' não está rodando"
    echo ""
    echo "Containers rodando:"
    docker ps --format "{{.Names}}" 2>/dev/null || echo "Nenhum container encontrado"
    exit 1
fi

echo "Container encontrado: $CONTAINER_NAME"
echo ""

echo "=== Testando conexão com PostgreSQL ==="
if ! docker exec $CONTAINER_NAME pg_isready -U postgres > /dev/null 2>&1; then
    echo "ERRO: PostgreSQL não está respondendo no container"
    echo "Verificando logs..."
    docker logs --tail 5 $CONTAINER_NAME 2>&1
    exit 1
fi

echo "PostgreSQL está respondendo"
echo ""

echo "=== Diagnóstico de Conexões PostgreSQL ==="
echo ""

MAX_CONN=$(docker exec $CONTAINER_NAME psql -U postgres -t -c "SHOW max_connections;" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "0")
CURRENT_CONN=$(docker exec $CONTAINER_NAME psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity;" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "0")
IDLE_CONN=$(docker exec $CONTAINER_NAME psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'idle';" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "0")
ACTIVE_CONN=$(docker exec $CONTAINER_NAME psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "0")

echo "Limite máximo (max_connections): $MAX_CONN"
echo "Conexões atuais: $CURRENT_CONN"
echo "- Ativas: $ACTIVE_CONN"
echo "- Idle: $IDLE_CONN"
echo ""

if [ "$MAX_CONN" != "0" ] && [ "$MAX_CONN" != "" ]; then
    PERCENT=$((CURRENT_CONN * 100 / MAX_CONN))
    echo "Uso: $PERCENT% ($CURRENT_CONN/$MAX_CONN)"
    echo ""
    
    if [ $PERCENT -gt 90 ]; then
        echo "CRÍTICO: Uso acima de 90%!"
    elif [ $PERCENT -gt 80 ]; then
        echo "ALERTA: Uso acima de 80%!"
    fi
else
    echo "AVISO: Não foi possível obter max_connections"
fi

echo ""
echo "=== Conexões por aplicação ==="
docker exec $CONTAINER_NAME psql -U postgres -c "
SELECT 
    COALESCE(application_name, 'NULL') as application_name,
    state,
    count(*) as connections
FROM pg_stat_activity 
WHERE datname = 'ai_saas_db'
GROUP BY application_name, state
ORDER BY connections DESC;
" 2>&1 | grep -v "WARNING" || echo "Erro ao obter informações"

echo ""
echo "=== Top 10 conexões mais antigas (idle) ==="
docker exec $CONTAINER_NAME psql -U postgres -c "
SELECT 
    pid,
    COALESCE(application_name, 'NULL') as application_name,
    state,
    state_change,
    now() - state_change as idle_time,
    LEFT(query, 50) as query_preview
FROM pg_stat_activity 
WHERE datname = 'ai_saas_db' 
  AND state = 'idle'
ORDER BY state_change ASC
LIMIT 10;
" 2>&1 | grep -v "WARNING" || echo "Erro ao obter informações"

echo ""
echo "=== Processos Python rodando ==="
echo "Backend workers (uvicorn):"
docker ps --filter "name=backend" --format "{{.Names}}" 2>/dev/null | wc -l | tr -d ' '
echo "Celery workers:"
docker ps --filter "name=worker" --format "{{.Names}}" 2>/dev/null | wc -l | tr -d ' '
echo "Celery beat:"
docker ps --filter "name=beat" --format "{{.Names}}" 2>/dev/null | wc -l | tr -d ' '
