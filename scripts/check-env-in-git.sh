#!/bin/bash
# scripts/check-env-in-git.sh
# Verifica se .env está no histórico do git e remove se encontrado

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Verificar .env no Histórico Git                ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════╝${NC}"
echo ""

cd "$PROJECT_DIR"

# 1. Verificar se .env está sendo rastreado atualmente
echo -e "${BLUE}1. Verificando se .env está sendo rastreado...${NC}"
if git ls-files --error-unmatch .env &>/dev/null; then
    echo -e "${RED}[ERROR] .env está sendo rastreado pelo git!${NC}"
    echo -e "${YELLOW}Removendo do índice...${NC}"
    git rm --cached .env
    echo -e "${GREEN}[OK] .env removido do índice${NC}"
else
    echo -e "${GREEN}[OK] .env não está sendo rastreado${NC}"
fi

# 2. Verificar se .env está no histórico
echo ""
echo -e "${BLUE}2. Verificando histórico do git...${NC}"
HISTORY=$(git log --all --full-history --oneline -- .env 2>/dev/null | head -10)

if [ -z "$HISTORY" ]; then
    echo -e "${GREEN}[OK] .env NÃO está no histórico do git${NC}"
    echo -e "${GREEN}[OK] Tudo seguro!${NC}"
    exit 0
fi

echo -e "${RED}[ERROR] .env ENCONTRADO no histórico do git!${NC}"
echo ""
echo -e "${YELLOW}Commits encontrados:${NC}"
echo "$HISTORY"
echo ""

# 3. Mostrar detalhes
echo -e "${BLUE}3. Detalhes dos commits:${NC}"
git log --all --full-history --pretty=format:"%h - %an, %ar : %s" --date=short -- .env | head -5
echo ""

# 4. Avisar sobre remoção
echo -e "${RED}[WARNING] ATENÇÃO: Remover .env do histórico requer rewrite do histórico${NC}"
echo -e "${YELLOW}Isso pode afetar colaboradores e requer force push${NC}"
echo ""
read -p "Deseja remover .env do histórico? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo -e "${YELLOW}Operação cancelada${NC}"
    echo ""
    echo -e "${BLUE}Para remover manualmente depois:${NC}"
    echo -e "${YELLOW}  git filter-repo --path .env --invert-paths${NC}"
    echo -e "${YELLOW}  git push --force --all${NC}"
    exit 0
fi

# 5. Verificar se git-filter-repo está instalado
if ! command -v git-filter-repo &> /dev/null; then
    echo -e "${YELLOW}git-filter-repo não encontrado${NC}"
    echo -e "${BLUE}Instalando...${NC}"
    
    # Tentar instalar
    if command -v pip3 &> /dev/null; then
        pip3 install git-filter-repo
    elif command -v pip &> /dev/null; then
        pip install git-filter-repo
    else
        echo -e "${RED}[ERROR] pip não encontrado${NC}"
        echo -e "${YELLOW}Instale git-filter-repo manualmente:${NC}"
        echo -e "${YELLOW}  pip install git-filter-repo${NC}"
        echo ""
        echo -e "${BLUE}Ou use git filter-branch (método legado):${NC}"
        read -p "Usar git filter-branch? (yes/no): " use_filter_branch
        if [ "$use_filter_branch" != "yes" ]; then
            exit 1
        fi
        USE_FILTER_BRANCH=true
    fi
fi

# 6. Fazer backup
echo ""
echo -e "${BLUE}4. Criando backup do repositório...${NC}"
BACKUP_DIR="../sky-poc-infra-backup-$(date +%Y%m%d_%H%M%S)"
cp -r "$PROJECT_DIR" "$BACKUP_DIR" 2>/dev/null || {
    echo -e "${YELLOW}[WARNING] Não foi possível criar backup completo${NC}"
    echo -e "${YELLOW}Fazendo backup do .git apenas...${NC}"
    BACKUP_DIR="../git-backup-$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    cp -r .git "$BACKUP_DIR/"
}
echo -e "${GREEN}[OK] Backup criado em: $BACKUP_DIR${NC}"

# 7. Remover do histórico
echo ""
echo -e "${BLUE}5. Removendo .env do histórico...${NC}"

if [ "$USE_FILTER_BRANCH" = "true" ]; then
    # Usar git filter-branch (método legado)
    echo -e "${YELLOW}Usando git filter-branch (método legado)...${NC}"
    git filter-branch --force --index-filter \
        "git rm --cached --ignore-unmatch .env" \
        --prune-empty --tag-name-filter cat -- --all
    
    # Limpar refs
    rm -rf .git/refs/original/
    git reflog expire --expire=now --all
    git gc --prune=now --aggressive
else
    # Usar git-filter-repo (método moderno e mais seguro)
    echo -e "${YELLOW}Usando git-filter-repo (método moderno)...${NC}"
    git filter-repo --path .env --invert-paths --force
fi

echo -e "${GREEN}[OK] .env removido do histórico${NC}"

# 8. Verificar novamente
echo ""
echo -e "${BLUE}6. Verificando novamente...${NC}"
HISTORY_AFTER=$(git log --all --full-history --oneline -- .env 2>/dev/null)

if [ -z "$HISTORY_AFTER" ]; then
    echo -e "${GREEN}[OK] .env removido com sucesso!${NC}"
else
    echo -e "${RED}[ERROR] Ainda há referências ao .env${NC}"
    exit 1
fi

# 9. Instruções finais
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}[OK] Remoção concluída!${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}[WARNING] PRÓXIMOS PASSOS IMPORTANTES:${NC}"
echo ""
echo -e "${BLUE}1. Avisar todos os colaboradores${NC}"
echo -e "${YELLOW}   Todos precisarão fazer:${NC}"
echo -e "${YELLOW}   git fetch origin${NC}"
echo -e "${YELLOW}   git reset --hard origin/main${NC}"
echo ""
echo -e "${BLUE}2. Force push (se estiver em repositório remoto)${NC}"
echo -e "${YELLOW}   git push --force --all${NC}"
echo -e "${YELLOW}   git push --force --tags${NC}"
echo ""
echo -e "${BLUE}3. Verificar que .env está no .gitignore${NC}"
echo ""
echo -e "${RED}[WARNING] ATENÇÃO: Force push reescreve o histórico remoto!${NC}"
echo -e "${RED}   Certifique-se de que todos os colaboradores foram avisados!${NC}"
echo ""

