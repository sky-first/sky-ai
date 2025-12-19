#!/bin/bash

# Health Check Avançado - DevOps
# Verifica saúde de todos os serviços

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

EXIT_CODE=0

check_service() {
    local name=$1
    local check_cmd=$2
    
    if eval "$check_cmd" > /dev/null 2>&1; then
        echo -e "${GREEN}${NC} $name"
        return 0
    else
        echo -e "${RED}${NC} $name"
        EXIT_CODE=1
        return 1
    fi
}

check_service_warning() {
    local name=$1
    local check_cmd=$2
    
    if eval "$check_cmd" > /dev/null 2>&1; then
        echo -e "${GREEN}${NC} $name"
        return 0
    else
        echo -e "${YELLOW}${NC} $name"
        return 1
    fi
}

echo "=========================================="
echo "Health Check - Infraestrutura"
echo "=========================================="
echo ""

echo "--- Containers Docker ---"
check_service "PostgreSQL Container" "docker ps | grep -q ai_saas_postgres_prod"
check_service "Redis Container" "docker ps | grep -q ai_saas_redis_prod"
check_service_warning "Backend Container" "docker ps | grep -q ai_saas_backend_prod"
check_service_warning "Worker Container" "docker ps | grep -q ai_saas_worker_prod"
check_service_warning "Beat Container" "docker ps | grep -q ai_saas_beat_prod"
echo ""

echo "--- Serviços ---"
check_service "PostgreSQL Respondendo" "docker exec ai_saas_postgres_prod pg_isready -U postgres"
check_service "Redis Respondendo" "docker exec ai_saas_redis_prod redis-cli ping | grep -q PONG"
check_service_warning "Backend API" "curl -f -s http://localhost:8000/health > /dev/null 2>&1 || curl -f -s http://localhost:8000/api/health > /dev/null 2>&1"
echo ""

echo "--- Recursos do Sistema ---"
# CPU
CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1 | cut -d',' -f1)
if (( $(echo "$CPU_USAGE < 80" | bc -l 2>/dev/null || echo "1") )); then
    echo -e "${GREEN}${NC} CPU: ${CPU_USAGE}%"
else
    echo -e "${YELLOW}${NC} CPU: ${CPU_USAGE}% (alto)"
fi

# Memória
MEM_USAGE=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100}')
if [ "$MEM_USAGE" -lt 80 ]; then
    echo -e "${GREEN}${NC} Memória: ${MEM_USAGE}%"
else
    echo -e "${YELLOW}${NC} Memória: ${MEM_USAGE}% (alto)"
fi

# Disco
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 80 ]; then
    echo -e "${GREEN}${NC} Disco: ${DISK_USAGE}%"
else
    echo -e "${YELLOW}${NC} Disco: ${DISK_USAGE}% (alto)"
fi
echo ""

echo "--- PostgreSQL ---"
if docker ps | grep -q ai_saas_postgres_prod; then
    CURRENT_CONN=$(docker exec ai_saas_postgres_prod psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity;" 2>/dev/null | tr -d ' ' || echo "0")
    MAX_CONN=$(docker exec ai_saas_postgres_prod psql -U postgres -t -c "SHOW max_connections;" 2>/dev/null | tr -d ' ' || echo "0")
    
    if [ "$MAX_CONN" != "0" ] && [ "$CURRENT_CONN" != "0" ]; then
        PERCENT=$((CURRENT_CONN * 100 / MAX_CONN))
        if [ $PERCENT -lt 80 ]; then
            echo -e "${GREEN}${NC} Conexões: $CURRENT_CONN/$MAX_CONN (${PERCENT}%)"
        else
            echo -e "${YELLOW}${NC} Conexões: $CURRENT_CONN/$MAX_CONN (${PERCENT}%)"
        fi
    fi
fi
echo ""

echo "--- Redis ---"
if docker ps | grep -q ai_saas_redis_prod; then
    REDIS_MEM=$(docker exec ai_saas_redis_prod redis-cli INFO memory 2>/dev/null | grep used_memory_human | cut -d: -f2 | tr -d '\r' || echo "N/A")
    echo -e "${GREEN}${NC} Memória usada: $REDIS_MEM"
fi
echo ""

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN} Todos os serviços críticos estão saudáveis${NC}"
else
    echo -e "${RED} Alguns serviços estão com problemas${NC}"
fi

exit $EXIT_CODE
