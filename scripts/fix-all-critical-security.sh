#!/bin/bash
# scripts/fix-all-critical-security.sh
# Script completo para corrigir todos os problemas críticos de segurança
# 1. Verificar .env no histórico git
# 2. Corrigir permissões do .env

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

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════╗"
echo "║     Correção Completa de Segurança                 ║"
echo "║     Problemas Críticos                             ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${NC}"

cd "$PROJECT_DIR"

# ============================================
# 1. VERIFICAR .env NO HISTÓRICO GIT
# ============================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}1. Verificando .env no histórico Git${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Verificar se está sendo rastreado
if git ls-files --error-unmatch .env &>/dev/null 2>&1; then
    echo -e "${RED}❌ .env está sendo rastreado pelo git!${NC}"
    echo -e "${YELLOW}Removendo do índice...${NC}"
    git rm --cached .env 2>/dev/null || true
    echo -e "${GREEN}✅ .env removido do índice${NC}"
else
    echo -e "${GREEN}✅ .env não está sendo rastreado${NC}"
fi

# Verificar histórico
HISTORY=$(git log --all --full-history --oneline -- .env 2>/dev/null | head -5)

if [ -z "$HISTORY" ]; then
    echo -e "${GREEN}✅ .env NÃO está no histórico do git${NC}"
    echo -e "${GREEN}✅ Tudo seguro!${NC}"
else
    echo -e "${RED}❌ .env ENCONTRADO no histórico do git!${NC}"
    echo ""
    echo -e "${YELLOW}Commits encontrados:${NC}"
    echo "$HISTORY"
    echo ""
    echo -e "${YELLOW}Para remover, execute:${NC}"
    echo -e "${BLUE}  ./scripts/check-env-in-git.sh${NC}"
    echo ""
    echo -e "${YELLOW}Ou manualmente:${NC}"
    echo -e "${BLUE}  git filter-repo --path .env --invert-paths${NC}"
fi

# ============================================
# 2. CORRIGIR PERMISSÕES DO .env
# ============================================
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}2. Verificando permissões do .env${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}.env não encontrado (isso é normal se ainda não foi criado)${NC}"
    echo -e "${BLUE}Quando criar, execute este script novamente${NC}"
else
    # Verificar permissões (Linux/Mac)
    if command -v stat &> /dev/null; then
        CURRENT_PERMS=$(stat -c "%a" "$ENV_FILE" 2>/dev/null || stat -f "%OLp" "$ENV_FILE" 2>/dev/null || echo "000")
        
        if [ "$CURRENT_PERMS" = "600" ] || [ "$CURRENT_PERMS" = "400" ]; then
            echo -e "${GREEN}✅ Permissões corretas: $CURRENT_PERMS${NC}"
        else
            echo -e "${YELLOW}Permissões atuais: $CURRENT_PERMS${NC}"
            echo -e "${BLUE}Corrigindo para 600...${NC}"
            chmod 600 "$ENV_FILE"
            
            NEW_PERMS=$(stat -c "%a" "$ENV_FILE" 2>/dev/null || stat -f "%OLp" "$ENV_FILE" 2>/dev/null || echo "000")
            if [ "$NEW_PERMS" = "600" ]; then
                echo -e "${GREEN}✅ Permissões corrigidas: $NEW_PERMS${NC}"
            else
                echo -e "${RED}❌ Erro ao corrigir permissões${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}stat não disponível (Windows?)${NC}"
        echo -e "${BLUE}Na VM Linux, execute: ./scripts/fix-env-permissions.sh${NC}"
    fi
fi

# ============================================
# 3. VERIFICAR .gitignore
# ============================================
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}3. Verificando .gitignore${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if grep -q "^\.env$" "$PROJECT_DIR/.gitignore" 2>/dev/null; then
    echo -e "${GREEN}✅ .env está no .gitignore${NC}"
else
    echo -e "${YELLOW}⚠️  .env não está no .gitignore${NC}"
    echo -e "${BLUE}Adicionando...${NC}"
    echo ".env" >> "$PROJECT_DIR/.gitignore"
    echo -e "${GREEN}✅ .env adicionado ao .gitignore${NC}"
fi

# ============================================
# RESUMO
# ============================================
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}✅ Verificação Completa Concluída${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ -n "$HISTORY" ]; then
    echo -e "${YELLOW}⚠️  AÇÃO NECESSÁRIA:${NC}"
    echo -e "${YELLOW}   .env encontrado no histórico. Execute:${NC}"
    echo -e "${BLUE}   ./scripts/check-env-in-git.sh${NC}"
    echo ""
fi

echo -e "${GREEN}✅ Todos os outros problemas foram corrigidos!${NC}"
echo ""

