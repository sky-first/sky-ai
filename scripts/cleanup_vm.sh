#!/bin/bash

# Script de limpeza específico para VM
# Remove arquivos de teste e scripts redundantes da raiz do projeto
# Uso: ./scripts/cleanup_vm.sh

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

log_warning() {
    echo -e "${YELLOW}  $1${NC}"
}

echo "=========================================="
echo "Limpeza de Arquivos Redundantes na VM"
echo "=========================================="
echo ""

cd ~/projeto/poc-deploy

# Arquivos de teste/tentativas anteriores (redundantes)
# O script correto está em scripts/postgres/install_pgvector_ai_saas_db.sh
FILES_TO_REMOVE=(
    # Scripts de instalação pgvector redundantes (raiz)
    "install_pgvector.sh"
    "install_pgvector_ai_saas_db.sh"  # Duplicado na raiz, correto está em scripts/postgres/
    "install_pgvector_fixed.sh"
    "install_pgvector_manual.sh"
    "install_and_fix_pgvector.sh"
    "install_pgvector_in_container.sh"
    "verify_and_install_pgvector.sh"
    "create_vector_extension.sh"
    
    # Scripts de verificação redundantes (raiz)
    "check_pgvector.sh"  # Duplicado, correto está em scripts/postgres/
    
    # Logs temporários
    "build.log"
    
    # Arquivos de exemplo/documentação extra (se existirem)
    "docker-compose.optimized.yml.example"
    "CHANGELOG_OTIMIZACOES.md"
    "OTIMIZACAO.md"
    "DEPLOYMENT.md"
    
    
    # Documentação extra
    "scripts/README.md"
)

log "Verificando arquivos para remover..."

REMOVED_COUNT=0
SKIPPED_COUNT=0

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

# Limpar pastas temporárias (se vazias)
for dir in logs backups tmp temp .docker; do
    if [ -d "$dir" ]; then
        FILE_COUNT=$(find "$dir" -type f 2>/dev/null | wc -l)
        if [ "$FILE_COUNT" -eq 0 ]; then
            log "Removendo pasta vazia: $dir"
            rmdir "$dir" 2>/dev/null && REMOVED_COUNT=$((REMOVED_COUNT + 1)) || true
        else
            log_warning "Mantendo $dir (contém $FILE_COUNT arquivo(s))"
        fi
    fi
done

# Limpar arquivos temporários do sistema
log "Limpando arquivos temporários..."
find . -maxdepth 1 -name "*.swp" -delete 2>/dev/null || true
find . -maxdepth 1 -name "*.swo" -delete 2>/dev/null || true
find . -maxdepth 1 -name "*~" -delete 2>/dev/null || true
find . -maxdepth 1 -name ".DS_Store" -delete 2>/dev/null || true

echo ""
echo "=========================================="
log_success "Limpeza concluída!"
echo "=========================================="
echo ""
log_success "Arquivos removidos: $REMOVED_COUNT"
echo ""
echo "Estrutura limpa mantida:"
echo "docker-compose.yml"
echo "docker-compose.infrastructure.yml"
echo "docker-compose.postgres-only.yml"
echo "scripts/ (scripts organizados)"
echo "scripts/postgres/install_pgvector_ai_saas_db.sh (script correto)"
echo "scripts/postgres/check_pgvector.sh (script correto)"
echo "README.md"
echo ""
