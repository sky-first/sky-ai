#!/bin/bash
# Script para verificar se tudo está pronto para o próximo deploy
# Pode ser executado via Azure CLI run-command ou diretamente na VM

set -euo pipefail

BASE="/home/azureuser/projeto"
if [ -d "$BASE/sky-poc-infra" ]; then
    INFRA_DIR="$BASE/sky-poc-infra"
elif [ -d "$BASE/poc-deploy" ]; then
    INFRA_DIR="$BASE/poc-deploy"
else
    echo "❌ ERRO: Diretório de infraestrutura não encontrado"
    exit 1
fi

cd "$INFRA_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

echo -e "${BLUE}=========================================="
echo "🔍 Verificação Pré-Deploy"
echo "==========================================${NC}"
echo ""

# 1. Verificar se .env existe
echo -e "${BLUE}1️⃣  Verificando arquivo .env...${NC}"
if [ -f .env ]; then
    echo -e "${GREEN}✅ .env existe${NC}"
    ls -lh .env
else
    echo -e "${RED}❌ .env NÃO existe${NC}"
    ((ERRORS++))
fi
echo ""

# 2. Verificar variáveis críticas
echo -e "${BLUE}2️⃣  Verificando variáveis críticas...${NC}"
MISSING_VARS=""

for var in POSTGRES_PASSWORD REDIS_PASSWORD JWT_SECRET_KEY ENCRYPTION_KEY; do
    if grep -q "^${var}=" .env 2>/dev/null; then
        VALUE=$(grep "^${var}=" .env | cut -d'=' -f2-)
        if [[ "$VALUE" == *"secure_password"* ]] || [[ "$VALUE" == *"generate"* ]] || [[ "$VALUE" == *"here"* ]] || [ -z "$VALUE" ]; then
            echo -e "${YELLOW}⚠️  ${var} tem valor placeholder ou vazio${NC}"
            MISSING_VARS="${MISSING_VARS} ${var}"
            ((WARNINGS++))
        else
            echo -e "${GREEN}✅ ${var} está configurado${NC}"
        fi
    else
        echo -e "${RED}❌ ${var} NÃO encontrado no .env${NC}"
        MISSING_VARS="${MISSING_VARS} ${var}"
        ((ERRORS++))
    fi
done
echo ""

# 3. Verificar NEXT_PUBLIC_API_URL
echo -e "${BLUE}3️⃣  Verificando NEXT_PUBLIC_API_URL...${NC}"
if grep -q "^NEXT_PUBLIC_API_URL=" .env 2>/dev/null; then
    API_URL=$(grep "^NEXT_PUBLIC_API_URL=" .env | cut -d'=' -f2-)
    echo -e "${GREEN}✅ NEXT_PUBLIC_API_URL=${API_URL}${NC}"
else
    echo -e "${YELLOW}⚠️  NEXT_PUBLIC_API_URL não encontrado (usará default)${NC}"
    ((WARNINGS++))
fi
echo ""

# 4. Verificar CORS_ORIGINS
echo -e "${BLUE}4️⃣  Verificando CORS_ORIGINS...${NC}"
if grep -q "^CORS_ORIGINS=" .env 2>/dev/null; then
    CORS=$(grep "^CORS_ORIGINS=" .env | cut -d'=' -f2-)
    if [[ "$CORS" == *"*"* ]] || [[ "$CORS" == *"0.0.0.0"* ]]; then
        echo -e "${RED}❌ CORS_ORIGINS contém '*' ou '0.0.0.0' (vulnerabilidade de segurança)${NC}"
        ((ERRORS++))
    else
        echo -e "${GREEN}✅ CORS_ORIGINS=${CORS}${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  CORS_ORIGINS não encontrado (usará default)${NC}"
    ((WARNINGS++))
fi
echo ""

# 5. Verificar containers
echo -e "${BLUE}5️⃣  Verificando containers Docker...${NC}"
if command -v docker >/dev/null 2>&1; then
    if sudo docker compose ps 2>/dev/null | grep -q "Up"; then
        echo -e "${GREEN}✅ Containers estão rodando${NC}"
        sudo docker compose ps 2>/dev/null | grep "Up" | head -5
    else
        echo -e "${YELLOW}⚠️  Nenhum container rodando (normal se ainda não fez deploy)${NC}"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}⚠️  Docker não encontrado${NC}"
    ((WARNINGS++))
fi
echo ""

# 6. Verificar permissões do .env
echo -e "${BLUE}6️⃣  Verificando permissões do .env...${NC}"
if [ -f .env ]; then
    PERMS=$(stat -c '%a' .env 2>/dev/null || stat -f '%A' .env 2>/dev/null || echo "")
    if [ "$PERMS" = "600" ]; then
        echo -e "${GREEN}✅ Permissões corretas (600)${NC}"
    else
        echo -e "${YELLOW}⚠️  Permissões: $PERMS (recomendado: 600)${NC}"
        echo "   Execute: chmod 600 .env"
        ((WARNINGS++))
    fi
fi
echo ""

# 7. Verificar estrutura de diretórios
echo -e "${BLUE}7️⃣  Verificando estrutura de diretórios...${NC}"
if [ -d "../sky-poc-backend" ] && [ -d "../sky-poc-frontend" ] && [ -d "../sky-poc-ai" ]; then
    echo -e "${GREEN}✅ Todos os repositórios encontrados${NC}"
else
    echo -e "${YELLOW}⚠️  Alguns repositórios podem estar faltando${NC}"
    [ ! -d "../sky-poc-backend" ] && echo "   - sky-poc-backend não encontrado"
    [ ! -d "../sky-poc-frontend" ] && echo "   - sky-poc-frontend não encontrado"
    [ ! -d "../sky-poc-ai" ] && echo "   - sky-poc-ai não encontrado"
    ((WARNINGS++))
fi
echo ""

# Resumo
echo -e "${BLUE}=========================================="
echo "📋 Resumo"
echo "==========================================${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ Tudo pronto para o próximo deploy!${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Pronto com $WARNINGS aviso(s)${NC}"
    echo "   Verifique os avisos acima, mas o deploy deve funcionar"
    exit 0
else
    echo -e "${RED}❌ Encontrados $ERRORS erro(s) e $WARNINGS aviso(s)${NC}"
    echo ""
    if [ -n "$MISSING_VARS" ]; then
        echo "Variáveis que precisam ser corrigidas:"
        echo "$MISSING_VARS"
        echo ""
        echo "Execute o script de geração de secrets:"
        echo "  bash scripts/azure/generate-secrets-on-vm.sh"
    fi
    exit 1
fi

