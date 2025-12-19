#!/bin/bash

set -e

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
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

# Listar backups disponíveis
list_backups() {
    BACKUP_BASE="$PROJECT_DIR/backups"
    
    if [ ! -d "$BACKUP_BASE" ]; then
        log_error "Nenhum backup encontrado"
        return 1
    fi
    
    echo "Backups disponíveis:"
    ls -1td "$BACKUP_BASE"/*/ 2>/dev/null | head -10 | while read dir; do
        BACKUP_DATE=$(basename "$dir")
        echo "- $BACKUP_DATE"
    done
}

# Restaurar backup
restore_backup() {
    BACKUP_DATE=$1
    
    if [ -z "$BACKUP_DATE" ]; then
        log_error "Data do backup não fornecida"
        echo "Uso: $0 <data_do_backup>"
        echo "Exemplo: $0 20240101_120000"
        list_backups
        exit 1
    fi
    
    BACKUP_DIR="$PROJECT_DIR/backups/$BACKUP_DATE"
    
    if [ ! -d "$BACKUP_DIR" ]; then
        log_error "Backup não encontrado: $BACKUP_DATE"
        list_backups
        exit 1
    fi
    
    log "Restaurando backup de: $BACKUP_DATE"
    
    CONTAINER_NAME="ai_saas_postgres_prod"
    
    # Restaurar PostgreSQL config
    if [ -f "$BACKUP_DIR/postgresql.conf.backup" ] && docker ps | grep -q "$CONTAINER_NAME"; then
        log "Restaurando configuração do PostgreSQL..."
        docker cp "$BACKUP_DIR/postgresql.conf.backup" "$CONTAINER_NAME:/var/lib/postgresql/data/postgresql.conf"
        docker restart "$CONTAINER_NAME"
        
        log "Aguardando PostgreSQL reiniciar..."
        for i in {1..30}; do
            if docker exec "$CONTAINER_NAME" pg_isready -U postgres > /dev/null 2>&1; then
                log_success "PostgreSQL restaurado e respondendo"
                break
            fi
            if [ $i -eq 30 ]; then
                log_error "PostgreSQL não está respondendo"
                exit 1
            fi
            sleep 2
        done
    fi
    
    # Restaurar docker-compose.yml
    if [ -f "$BACKUP_DIR/docker-compose.yml.backup" ]; then
        log "Restaurando docker-compose.yml..."
        cp "$BACKUP_DIR/docker-compose.yml.backup" "$PROJECT_DIR/docker-compose.yml"
        log_success "docker-compose.yml restaurado"
        log_warning "Reinicie os containers: docker compose down && docker compose up -d"
    fi
    
    log_success "Rollback concluído!"
}

# Menu interativo
if [ -z "$1" ]; then
    echo "=========================================="
    echo "Rollback de Otimizações"
    echo "=========================================="
    echo ""
    list_backups
    echo ""
    read -p "Digite a data do backup para restaurar (formato: YYYYMMDD_HHMMSS): " BACKUP_DATE
    restore_backup "$BACKUP_DATE"
else
    restore_backup "$1"
fi
