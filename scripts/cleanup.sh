#!/bin/bash

# Script de limpeza - Remove apenas arquivos desnecessários
# Uso: ./scripts/cleanup.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"
}

log_success() {
    echo -e "${GREEN} $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}  $1${NC}"
}

log_info() {
    echo -e "${GREEN}ℹ  $1${NC}"
}

echo "=========================================="
echo "Limpeza de Arquivos Desnecessários"
echo "=========================================="
echo ""

cd "$PROJECT_DIR"

# Lista de arquivos a remover (apenas desnecessários)
FILES_TO_REMOVE=(
    # Arquivo de exemplo (não usado em produção)
    "docker-compose.optimized.yml.example"
    
    # Documentação excessiva (manter apenas README.md principal)
    "CHANGELOG_OTIMIZACOES.md"
    "OTIMIZACAO.md"
    "DEPLOYMENT.md"
    "scripts/README.md"
)

# Pastas temporárias (se existirem e estiverem vazias)
DIRS_TO_REMOVE=(
    "logs"
    "backups"
    "tmp"
    "temp"
    ".docker"
)

log "Verificando arquivos para remover..."

REMOVED_COUNT=0
SKIPPED_COUNT=0

# Remover arquivos
for file in "${FILES_TO_REMOVE[@]}"; do
    if [ -f "$file" ]; then
        log "Removendo: $file"
        rm -f "$file"
        REMOVED_COUNT=$((REMOVED_COUNT + 1))
        log_success "Removido: $file"
    else
        SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    fi
done

# Remover pastas temporárias (apenas se vazias)
for dir in "${DIRS_TO_REMOVE[@]}"; do
    if [ -d "$dir" ]; then
        FILE_COUNT=$(find "$dir" -type f 2>/dev/null | wc -l)
        if [ "$FILE_COUNT" -gt 0 ]; then
            log_warning "Pasta $dir contém $FILE_COUNT arquivo(s) - mantendo"
        else
            log "Removendo pasta vazia: $dir"
            rmdir "$dir" 2>/dev/null && REMOVED_COUNT=$((REMOVED_COUNT + 1)) || true
        fi
    fi
done

# Limpar arquivos temporários do sistema
log "Limpando arquivos temporários..."
find . -name "*.swp" -delete 2>/dev/null || true
find . -name "*.swo" -delete 2>/dev/null || true
find . -name "*~" -delete 2>/dev/null || true
find . -name ".DS_Store" -delete 2>/dev/null || true

echo ""
echo "=========================================="
log_success "Limpeza concluída!"
echo "=========================================="
echo ""
log_info "Arquivos removidos: $REMOVED_COUNT"
echo ""
echo "Arquivos mantidos (essenciais):"
echo "docker-compose.yml"
echo "docker-compose.infrastructure.yml"
echo "docker-compose.postgres-only.yml"
echo "scripts/ (scripts funcionais)"
echo "README.md"
echo ".gitignore"
echo ""
