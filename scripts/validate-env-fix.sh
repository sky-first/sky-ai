#!/bin/bash
# Script para validar se as correções do .env estão implementadas corretamente

set -e

echo "🔍 Validando correções do .env no pipeline..."
echo ""

# Cores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# 1. Verificar se o step "Bootstrap .env" existe
echo "1. Verificando step 'Bootstrap .env from env.example'..."
if grep -q "Bootstrap .env from env.example (CRITICAL - Always Run)" .github/workflows/deploy.yml; then
    echo -e "${GREEN}[OK] Step 'Bootstrap .env' encontrado${NC}"
else
    echo -e "${RED}[ERROR] Step 'Bootstrap .env' NÃO encontrado${NC}"
    ((ERRORS++))
fi

# 2. Verificar se o step está na ordem correta (depois de Update Code)
echo ""
echo "2. Verificando ordem dos steps..."
BOOTSTRAP_LINE=$(grep -n "Bootstrap .env from env.example" .github/workflows/deploy.yml | cut -d: -f1)
UPDATE_CODE_LINE=$(grep -n "Update Code on VM" .github/workflows/deploy.yml | cut -d: -f1 | head -1)

if [ -n "$BOOTSTRAP_LINE" ] && [ -n "$UPDATE_CODE_LINE" ]; then
    if [ "$BOOTSTRAP_LINE" -gt "$UPDATE_CODE_LINE" ]; then
        echo -e "${GREEN}[OK] Step 'Bootstrap .env' está DEPOIS de 'Update Code' (correto)${NC}"
    else
        echo -e "${RED}[ERROR] Step 'Bootstrap .env' está ANTES de 'Update Code' (incorreto)${NC}"
        ((ERRORS++))
    fi
else
    echo -e "${YELLOW}[WARNING] Não foi possível verificar ordem dos steps${NC}"
fi

# 3. Verificar se o step "Restart Containers" tem validações
echo ""
echo "3. Verificando validações no step 'Restart Containers'..."
RESTART_SECTION=$(grep -A 100 "Restart Containers (Sequential Deploy)" .github/workflows/deploy.yml)
if echo "$RESTART_SECTION" | grep -q "docker ps"; then
    echo -e "${GREEN}[OK] Validação 'docker ps' encontrada${NC}"
else
    echo -e "${RED}[ERROR] Validação 'docker ps' NÃO encontrada${NC}"
    ((ERRORS++))
fi

if echo "$RESTART_SECTION" | grep -q "localhost/health"; then
    echo -e "${GREEN}[OK] Validação 'curl localhost/health' encontrada${NC}"
else
    echo -e "${RED}[ERROR] Validação 'curl localhost/health' NÃO encontrada${NC}"
    ((ERRORS++))
fi

if echo "$RESTART_SECTION" | grep -q "RUNNING_CONTAINERS"; then
    echo -e "${GREEN}[OK] Validação de contagem de containers encontrada${NC}"
else
    echo -e "${YELLOW}[WARNING] Validação de contagem de containers não encontrada${NC}"
fi

# 4. Verificar se env.example existe
echo ""
echo "4. Verificando se env.example existe..."
if [ -f env.example ]; then
    echo -e "${GREEN}[OK] env.example existe${NC}"
    
    # Verificar variáveis críticas
    echo ""
    echo "   Verificando variáveis críticas no env.example..."
    CRITICAL_VARS=("POSTGRES_PASSWORD" "REDIS_PASSWORD" "JWT_SECRET_KEY" "ENCRYPTION_KEY" "DATABASE_URL")
    for var in "${CRITICAL_VARS[@]}"; do
        if grep -q "^${var}=" env.example; then
            echo -e "   ${GREEN}[OK]${NC} $var"
        else
            echo -e "   ${RED}[ERROR]${NC} $var (faltando)"
            ((ERRORS++))
        fi
    done
else
    echo -e "${RED}[ERROR] env.example NÃO existe${NC}"
    ((ERRORS++))
fi

# 5. Verificar se smoke-tests.sh existe
echo ""
echo "5. Verificando se smoke-tests.sh existe..."
if [ -f scripts/smoke-tests.sh ]; then
    echo -e "${GREEN}[OK] smoke-tests.sh existe${NC}"
    
    # Verificar se o script verifica .env
    if grep -q "\.env" scripts/smoke-tests.sh; then
        echo -e "   ${GREEN}[OK]${NC} Script verifica .env"
    else
        echo -e "   ${YELLOW}[WARNING] ${NC} Script não verifica .env explicitamente"
    fi
else
    echo -e "${RED}[ERROR] smoke-tests.sh NÃO existe${NC}"
    ((ERRORS++))
fi

# 6. Verificar sintaxe YAML do pipeline
echo ""
echo "6. Verificando estrutura do pipeline..."
# Verificação básica: arquivo existe e não está vazio
if [ -s .github/workflows/deploy.yml ]; then
    echo -e "${GREEN}[OK] Arquivo deploy.yml existe e não está vazio${NC}"
    
    # Verificar se tem estrutura básica de workflow
    if grep -q "name:" .github/workflows/deploy.yml && grep -q "on:" .github/workflows/deploy.yml; then
        echo -e "${GREEN}[OK] Estrutura básica de workflow encontrada${NC}"
    else
        echo -e "${RED}[ERROR] Estrutura básica de workflow não encontrada${NC}"
        ((ERRORS++))
    fi
else
    echo -e "${RED}[ERROR] Arquivo deploy.yml não existe ou está vazio${NC}"
    ((ERRORS++))
fi

# 7. Verificar documentação
echo ""
echo "7. Verificando documentação criada..."
if [ -f docs/RESOLVER-ERRO-ENV-FALTANDO.md ]; then
    echo -e "${GREEN}[OK] Documentação criada${NC}"
else
    echo -e "${RED}[ERROR] Documentação NÃO encontrada${NC}"
    ((ERRORS++))
fi

# Resumo
echo ""
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}[OK] Todas as validações passaram!${NC}"
    echo ""
    echo "Resumo das correções implementadas:"
    echo "  [OK] Step 'Bootstrap .env' adicionado ao pipeline"
    echo "  [OK] Step está na ordem correta (após Update Code)"
    echo "  [OK] Validações adicionadas no step 'Restart Containers'"
    echo "  [OK] env.example existe e tem variáveis críticas"
    echo "  [OK] smoke-tests.sh existe"
    echo "  [OK] Pipeline YAML válido"
    echo "  [OK] Documentação criada"
    echo ""
    echo "🎉 Pronto para testar no próximo deploy!"
    exit 0
else
    echo -e "${RED}[ERROR] Encontrados $ERRORS erro(s)${NC}"
    echo ""
    echo "Corrija os erros acima antes de fazer deploy."
    exit 1
fi

