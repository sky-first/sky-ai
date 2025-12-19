#!/bin/bash

# Script para aplicar otimizações críticas rapidamente
# Uso: ./scripts/apply_critical_optimizations.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"
}

log_success() {
    echo -e "${GREEN} $1${NC}"
}

log_error() {
    echo -e "${RED} $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}  $1${NC}"
}

echo "=========================================="
echo "Aplicando Otimizações Críticas"
echo "=========================================="
echo ""

# 1. Verificar se está no diretório correto
if [ ! -f "docker-compose.yml" ]; then
    log_error "Execute este script do diretório poc-deploy"
    exit 1
fi

# 2. Otimizar PostgreSQL
log "1. Otimizando PostgreSQL..."
if [ -f "scripts/postgres/configure_postgres_safe.sh" ]; then
    ./scripts/postgres/configure_postgres_safe.sh 300 2
    log_success "PostgreSQL otimizado"
else
    log_warning "Script de otimização PostgreSQL não encontrado"
    log "Execute manualmente: ./scripts/postgres/configure_postgres_safe.sh 300 2"
fi

echo ""

# 3. Reiniciar containers com novas configurações
log "2. Reiniciando containers com novas configurações..."
log_warning "Isso vai reiniciar todos os containers!"

read -p "Continuar? (s/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Ss]$ ]]; then
    log "Operação cancelada"
    exit 0
fi

log "Parando containers..."
docker compose down

log "Iniciando containers..."
docker compose up -d

log "Aguardando serviços iniciarem..."
sleep 15

echo ""

# 4. Verificar saúde
log "3. Verificando saúde dos serviços..."
if [ -f "scripts/health_check.sh" ]; then
    ./scripts/health_check.sh
else
    log_warning "Script de health check não encontrado"
    log "Verificando manualmente..."
    docker ps
fi

echo ""
echo "=========================================="
log_success "Otimizações aplicadas!"
echo "=========================================="
echo ""
echo "Próximos passos:"
echo "1. Execute: ./scripts/postgres/check_postgres_connections.sh"
echo "2. Execute: ./scripts/monitor_resources.sh"
echo "3. Monitore por 30 minutos"
echo ""
echo "Nota: Ajuste o pool_size no código do backend para reduzir conexões"
echo "Recomendado: pool_size=2, max_overflow=5"
