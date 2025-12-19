#!/bin/bash

CONTAINER_NAME="ai_saas_redis_prod"

if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "ERRO: Container Redis não está rodando"
    exit 1
fi

echo "=== Monitoramento Redis ==="
echo ""

echo "1. Informações do Servidor:"
docker exec $CONTAINER_NAME redis-cli --raw INFO server 2>/dev/null | grep -E "redis_version|uptime_in_days|process_id" || echo "Erro ao conectar"
echo ""

echo "2. Uso de Memória:"
docker exec $CONTAINER_NAME redis-cli --raw INFO memory 2>/dev/null | grep -E "used_memory_human|used_memory_peak_human|maxmemory_human|mem_fragmentation_ratio" || echo "Erro ao conectar"
echo ""

echo "3. Estatísticas:"
docker exec $CONTAINER_NAME redis-cli --raw INFO stats 2>/dev/null | grep -E "total_connections_received|total_commands_processed|keyspace_hits|keyspace_misses" || echo "Erro ao conectar"
echo ""

echo "4. Hit Rate:"
HITS=$(docker exec $CONTAINER_NAME redis-cli --raw INFO stats 2>/dev/null | grep "keyspace_hits" | cut -d: -f2 | tr -d '\r' || echo "0")
MISSES=$(docker exec $CONTAINER_NAME redis-cli --raw INFO stats 2>/dev/null | grep "keyspace_misses" | cut -d: -f2 | tr -d '\r' || echo "0")
if [ "$HITS" != "0" ] && [ "$MISSES" != "0" ]; then
    TOTAL=$((HITS + MISSES))
    HIT_RATE=$((HITS * 100 / TOTAL))
    echo "Hit Rate: ${HIT_RATE}%"
else
    echo "Hit Rate: N/A (sem dados suficientes)"
fi
echo ""

echo "5. Número de Chaves por Database:"
docker exec $CONTAINER_NAME redis-cli --raw INFO keyspace 2>/dev/null || echo "Erro ao conectar"
echo ""

echo "6. Conexões Clientes:"
docker exec $CONTAINER_NAME redis-cli --raw INFO clients 2>/dev/null | grep -E "connected_clients|blocked_clients" || echo "Erro ao conectar"
