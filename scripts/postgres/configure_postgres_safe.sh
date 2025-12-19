#!/bin/bash

set -e

CONTAINER_NAME="ai_saas_postgres_prod"
MAX_CONNECTIONS=${1:-300}
WORK_MEM_MB=${2:-2}

echo "=== Configuração Segura do PostgreSQL ==="
echo ""

if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "ERRO: Container não está rodando"
    exit 1
fi

echo "1. Verificando memória do servidor..."
TOTAL_MEM=$(free -m | awk '/^Mem:/ {print $2}')
AVAIL_MEM=$(free -m | awk '/^Mem:/ {print $7}')
echo "Memória total: ${TOTAL_MEM}MB"
echo "Memória disponível: ${AVAIL_MEM}MB"
echo ""

# Calcular memória necessária
# Cada conexão pode usar até work_mem em operações complexas
# Estimativa conservadora: 50% das conexões usando work_mem simultaneamente
ESTIMATED_MEM=$((MAX_CONNECTIONS * WORK_MEM_MB / 2))
echo "2. Estimativa de memória necessária:"
echo "max_connections: $MAX_CONNECTIONS"
echo "work_mem: ${WORK_MEM_MB}MB"
echo "Memória estimada (50% conexões ativas): ${ESTIMATED_MEM}MB"
echo ""

if [ $ESTIMATED_MEM -gt $AVAIL_MEM ]; then
    echo "AVISO: Memória estimada (${ESTIMATED_MEM}MB) excede disponível (${AVAIL_MEM}MB)"
    echo "Considere reduzir max_connections ou work_mem"
    echo "Ou aumentar a memória do servidor"
    read -p "   Continuar mesmo assim? (s/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Ss]$ ]]; then
        echo "Operação cancelada"
        exit 1
    fi
else
    echo "Memória suficiente disponível"
fi

echo ""
echo "3. Verificando configurações atuais..."
CURRENT_MAX=$(docker exec $CONTAINER_NAME sh -c "grep '^max_connections' /var/lib/postgresql/data/postgresql.conf 2>/dev/null | head -1" || echo "não encontrado")
CURRENT_WORK_MEM=$(docker exec $CONTAINER_NAME sh -c "grep '^work_mem' /var/lib/postgresql/data/postgresql.conf 2>/dev/null | head -1" || echo "não encontrado")
echo "max_connections atual: $CURRENT_MAX"
echo "work_mem atual: $CURRENT_WORK_MEM"
echo ""

echo "4. Configurando max_connections = $MAX_CONNECTIONS..."
docker exec $CONTAINER_NAME sh -c "
    MAX_CONN=$MAX_CONNECTIONS
    if grep -q \"^max_connections\" /var/lib/postgresql/data/postgresql.conf; then
        sed -i \"s/^max_connections = [0-9]*/max_connections = \$MAX_CONN/g\" /var/lib/postgresql/data/postgresql.conf
        echo \"max_connections atualizado para \$MAX_CONN\"
    elif grep -q \"^#max_connections\" /var/lib/postgresql/data/postgresql.conf; then
        sed -i \"s/^#max_connections = [0-9]*/max_connections = \$MAX_CONN/g\" /var/lib/postgresql/data/postgresql.conf
        echo \"max_connections descomentado e configurado para \$MAX_CONN\"
    else
        echo '' >> /var/lib/postgresql/data/postgresql.conf
        echo '# Maximum number of connections' >> /var/lib/postgresql/data/postgresql.conf
        echo \"max_connections = \$MAX_CONN\" >> /var/lib/postgresql/data/postgresql.conf
        echo \"max_connections adicionado: \$MAX_CONN\"
    fi
"

echo ""
echo "5. Configurando work_mem = ${WORK_MEM_MB}MB..."
docker exec $CONTAINER_NAME sh -c "
    WORK_MEM_VAL=${WORK_MEM_MB}MB
    if grep -q \"^work_mem\" /var/lib/postgresql/data/postgresql.conf; then
        sed -i \"s/^work_mem = [0-9]*[a-zA-Z]*/work_mem = \$WORK_MEM_VAL/g\" /var/lib/postgresql/data/postgresql.conf
        echo \"work_mem atualizado para \$WORK_MEM_VAL\"
    elif grep -q \"^#work_mem\" /var/lib/postgresql/data/postgresql.conf; then
        sed -i \"s/^#work_mem = [0-9]*[a-zA-Z]*/work_mem = \$WORK_MEM_VAL/g\" /var/lib/postgresql/data/postgresql.conf
        echo \"work_mem descomentado e configurado para \$WORK_MEM_VAL\"
    else
        echo '' >> /var/lib/postgresql/data/postgresql.conf
        echo '# Work memory for operations' >> /var/lib/postgresql/data/postgresql.conf
        echo \"work_mem = \$WORK_MEM_VAL\" >> /var/lib/postgresql/data/postgresql.conf
        echo \"work_mem adicionado: \$WORK_MEM_VAL\"
    fi
"

echo ""
echo "6. Verificando configurações aplicadas..."
echo "max_connections:"
docker exec $CONTAINER_NAME sh -c "grep '^max_connections' /var/lib/postgresql/data/postgresql.conf" || echo "ERRO: Não encontrado"
echo "work_mem:"
docker exec $CONTAINER_NAME sh -c "grep '^work_mem' /var/lib/postgresql/data/postgresql.conf" || echo "ERRO: Não encontrado"
echo ""

echo "7. Reiniciando container PostgreSQL..."
docker restart $CONTAINER_NAME
echo "Aguardando PostgreSQL iniciar..."
sleep 10

echo ""
echo "8. Verificando se PostgreSQL está respondendo..."
for i in {1..10}; do
    if docker exec $CONTAINER_NAME pg_isready -U postgres > /dev/null 2>&1; then
        echo "PostgreSQL está respondendo!"
        break
    fi
    if [ $i -eq 10 ]; then
        echo "PostgreSQL não está respondendo após 20 segundos"
        echo "Verifique os logs: docker logs $CONTAINER_NAME"
        exit 1
    fi
    echo "Tentativa $i/10 - aguardando..."
    sleep 2
done

echo ""
echo "9. Verificando configurações aplicadas no PostgreSQL..."
MAX_CONN=$(docker exec $CONTAINER_NAME psql -U postgres -t -c "SHOW max_connections;" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "erro")
WORK_MEM=$(docker exec $CONTAINER_NAME psql -U postgres -t -c "SHOW work_mem;" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "erro")

if [ "$MAX_CONN" != "erro" ] && [ "$MAX_CONN" != "" ]; then
    echo "max_connections: $MAX_CONN"
else
    echo "Não foi possível verificar max_connections via psql"
fi

if [ "$WORK_MEM" != "erro" ] && [ "$WORK_MEM" != "" ]; then
    echo "work_mem: $WORK_MEM"
else
    echo "Não foi possível verificar work_mem via psql"
fi

echo ""
echo "=== Configuração concluída! ==="
echo ""
echo "Resumo:"
echo "max_connections: $MAX_CONNECTIONS"
echo "work_mem: ${WORK_MEM_MB}MB"
echo "Memória estimada: ${ESTIMATED_MEM}MB"
echo ""
echo "Próximos passos:"
echo "1. Execute: ./scripts/postgres/check_postgres_connections.sh"
echo "2. Monitore o uso de memória: free -m"
echo "3. Ajuste o pool_size no backend para evitar muitas conexões"
echo "4. Monitore conexões idle que não estão sendo fechadas"
