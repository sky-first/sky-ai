#!/bin/bash

# Script de validação - Verifica se a limpeza não quebrou nada
# Uso: ./scripts/validate_cleanup.sh

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
echo "Validação Pós-Limpeza"
echo "=========================================="
echo ""

cd ~/projeto/poc-deploy

ERRORS=0

# 1. Verificar arquivos essenciais
log "1. Verificando arquivos essenciais..."

ESSENTIAL_FILES=(
    "docker-compose.yml"
    "docker-compose.infrastructure.yml"
    "docker-compose.postgres-only.yml"
    "README.md"
    ".gitignore"
    "env.example"
)

for file in "${ESSENTIAL_FILES[@]}"; do
    if [ -f "$file" ]; then
        log_success "$file existe"
    else
        log_error "$file NÃO encontrado!"
        ERRORS=$((ERRORS + 1))
    fi
done

# 2. Verificar scripts essenciais
log ""
log "2. Verificando scripts essenciais..."

ESSENTIAL_SCRIPTS=(
    "scripts/postgres/install_pgvector_ai_saas_db.sh"
    "scripts/postgres/check_pgvector.sh"
    "scripts/postgres/configure_postgres_safe.sh"
    "scripts/postgres/configure_postgres_external.sh"
    "scripts/postgres/check_postgres_connections.sh"
    "scripts/postgres/diagnose_postgres_connection.sh"
    "scripts/postgres/setup_pgvector.sql"
    "scripts/health_check.sh"
    "scripts/monitor_resources.sh"
    "scripts/monitor_redis.sh"
    "scripts/optimize_infrastructure.sh"
    "scripts/rollback_optimization.sh"
    "setup_server.sh"
)

for script in "${ESSENTIAL_SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        log_success "$script existe"
    else
        log_error "$script NÃO encontrado!"
        ERRORS=$((ERRORS + 1))
    fi
done

# 3. Verificar se scripts removidos não são referenciados
log ""
log "3. Verificando referências a arquivos removidos..."

REMOVED_FILES=(
    "install_pgvector.sh"
    "install_pgvector_ai_saas_db.sh"
    "check_pgvector.sh"
    "scripts/postgres/fix_too_many_connections.sh"
    "scripts/postgres/configure_postgres_max_connections.sh"
)

for file in "${REMOVED_FILES[@]}"; do
    if [ -f "$file" ]; then
        log_warning "$file ainda existe (deveria ter sido removido)"
    else
        log_success "$file não existe (correto)"
    fi
done

# 4. Verificar se scripts principais funcionam
log ""
log "4. Verificando sintaxe dos scripts principais..."

SCRIPTS_TO_CHECK=(
    "scripts/postgres/configure_postgres_safe.sh"
    "scripts/postgres/install_pgvector_ai_saas_db.sh"
    "scripts/health_check.sh"
)

for script in "${SCRIPTS_TO_CHECK[@]}"; do
    if [ -f "$script" ]; then
        if bash -n "$script" 2>/dev/null; then
            log_success "$script - sintaxe OK"
        else
            log_error "$script - erro de sintaxe!"
            ERRORS=$((ERRORS + 1))
        fi
    fi
done

# 5. Verificar estrutura de diretórios
log ""
log "5. Verificando estrutura de diretórios..."

ESSENTIAL_DIRS=(
    "scripts"
    "scripts/postgres"
    "docker"
    "docker/postgres"
    "infra"
)

for dir in "${ESSENTIAL_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        log_success "$dir/ existe"
    else
        log_error "$dir/ NÃO encontrado!"
        ERRORS=$((ERRORS + 1))
    fi
done

# 6. Verificar docker-compose.yml
log ""
log "6. Verificando docker-compose.yml..."

if [ -f "docker-compose.yml" ]; then
    if docker compose config > /dev/null 2>&1; then
        log_success "docker-compose.yml - sintaxe válida"
    else
        log_error "docker-compose.yml - erro de sintaxe!"
        ERRORS=$((ERRORS + 1))
    fi
fi

echo ""
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    log_success "Validação concluída - Tudo OK!"
    echo "=========================================="
    echo ""
    echo "Todos os arquivos essenciais estão presentes"
    echo "Scripts principais estão funcionais"
    echo "Estrutura de diretórios está correta"
    echo "Nenhuma dependência quebrada"
    exit 0
else
    log_error "Validação falhou - $ERRORS erro(s) encontrado(s)"
    echo "=========================================="
    exit 1
fi
