#!/bin/bash
# scripts/health-check-complete.sh
# Health check completo de todos os serviços
# Pode ser executado localmente ou na VM

set -e

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

FAILED=0
WARNINGS=0

check_service() {
    local name=$1
    local check=$2
    local is_critical=${3:-true}
    
    echo -n "Verificando $name... "
    
    if eval "$check" &>/dev/null; then
        echo -e "${GREEN}✅ OK${NC}"
        return 0
    else
        if [ "$is_critical" = "true" ]; then
            echo -e "${RED}❌ FALHOU${NC}"
            FAILED=$((FAILED + 1))
            return 1
        else
            echo -e "${YELLOW}⚠️  AVISO${NC}"
            WARNINGS=$((WARNINGS + 1))
            return 0
        fi
    fi
}

echo -e "${BLUE}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Health Check Completo                          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════╝${NC}"
echo ""

# Verificar se está na VM ou local
if [ -f "/home/azureuser/projeto/poc-deploy/docker-compose.yml" ] || \
   [ -f "~/projeto/poc-deploy/docker-compose.yml" ]; then
    # Na VM
    COMPOSE_CMD="docker compose"
    COMPOSE_FILE="docker-compose.yml"
    cd ~/projeto/poc-deploy 2>/dev/null || cd /home/azureuser/projeto/poc-deploy
else
    # Local
    COMPOSE_CMD="docker compose"
    COMPOSE_FILE="docker-compose.yml"
fi

# Verificar Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker não está instalado${NC}"
    exit 1
fi

# Verificar containers rodando
echo -e "${BLUE}Verificando containers...${NC}"
if ! $COMPOSE_CMD ps | grep -q "Up"; then
    echo -e "${RED}❌ Nenhum container está rodando${NC}"
    exit 1
fi

echo ""

# PostgreSQL
check_service "PostgreSQL" \
    "docker exec ai_saas_postgres_prod pg_isready -U postgres" \
    true

# Redis
check_service "Redis" \
    "docker exec ai_saas_redis_prod redis-cli ping | grep -q PONG" \
    true

# Backend
check_service "Backend (porta 8000)" \
    "curl -f -s http://localhost:8000/health > /dev/null 2>&1 || curl -f -s http://localhost:8000/api/health > /dev/null 2>&1 || curl -f -s http://localhost:8000/ > /dev/null 2>&1" \
    false

# Frontend
check_service "Frontend (porta 3000)" \
    "curl -f -s http://localhost:3000 > /dev/null 2>&1" \
    false

# Nginx (se estiver no compose)
if $COMPOSE_CMD ps | grep -q "proxy\|nginx"; then
    check_service "Nginx (porta 80)" \
        "curl -f -s http://localhost:80 > /dev/null 2>&1 || curl -f -s http://localhost > /dev/null 2>&1" \
        false
fi

# Worker (se existir)
if docker ps | grep -q "worker"; then
    check_service "Celery Worker" \
        "docker exec ai_saas_worker_prod pgrep -f 'celery worker' > /dev/null" \
        false
fi

# Beat (se existir)
if docker ps | grep -q "beat"; then
    check_service "Celery Beat" \
        "docker exec ai_saas_beat_prod pgrep -f 'celery beat' > /dev/null" \
        false
fi

# Resumo
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ $FAILED -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ Todos os serviços estão saudáveis${NC}"
    exit 0
elif [ $FAILED -eq 0 ]; then
    echo -e "${YELLOW}⚠️  $WARNINGS aviso(s), mas serviços críticos OK${NC}"
    exit 0
else
    echo -e "${RED}❌ $FAILED serviço(s) crítico(s) falharam${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}   + $WARNINGS aviso(s)${NC}"
    fi
    exit 1
fi

