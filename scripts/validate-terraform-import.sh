#!/bin/bash
# Script de validação para garantir que as correções do terraform import estão corretas

set -euo pipefail

echo "=== Validação das Correções do Terraform Import ==="
echo ""

# Cores para output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Função para verificar se um padrão existe no arquivo
check_pattern() {
    local file="$1"
    local pattern="$2"
    local description="$3"
    
    if grep -q "$pattern" "$file"; then
        echo -e "${GREEN}✅${NC} $description"
        return 0
    else
        echo -e "${RED}❌${NC} $description"
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

# Função para verificar se um padrão NÃO existe (anti-pattern)
check_no_pattern() {
    local file="$1"
    local pattern="$2"
    local description="$3"
    
    if ! grep -q "$pattern" "$file"; then
        echo -e "${GREEN}✅${NC} $description"
        return 0
    else
        echo -e "${RED}❌${NC} $description"
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

WORKFLOW_FILE=".github/workflows/deploy.yml"

if [ ! -f "$WORKFLOW_FILE" ]; then
    echo -e "${RED}ERRO: Arquivo não encontrado: $WORKFLOW_FILE${NC}"
    exit 1
fi

echo "Validando arquivo: $WORKFLOW_FILE"
echo ""

# ============================================
# Validações do Step: Sync Existing Resources
# ============================================
echo "=== Validações: Sync Existing Resources ==="

# Verificar se VAR_ARGS está sendo usado (não IMPORT_VARS)
check_pattern "$WORKFLOW_FILE" "VAR_ARGS=" "Array VAR_ARGS está sendo usado"
check_no_pattern "$WORKFLOW_FILE" "IMPORT_VARS=" "Array IMPORT_VARS antigo não está sendo usado"

# Verificar expansão correta do array
check_pattern "$WORKFLOW_FILE" '\"\$\{VAR_ARGS\[@\]\}\"' "Array VAR_ARGS está sendo expandido corretamente"

# Verificar se variáveis estão sendo adicionadas ao array
check_pattern "$WORKFLOW_FILE" "VAR_ARGS\+=" "Variáveis estão sendo adicionadas ao array"

# Verificar se não há set +e antes do import (fail-fast)
check_pattern "$WORKFLOW_FILE" "terraform import" "Comando terraform import existe"
# Verificar que não há set +e imediatamente antes do import
if grep -A 5 "terraform import" "$WORKFLOW_FILE" | grep -B 2 "terraform import" | grep -q "set +e"; then
    echo -e "${RED}❌${NC} set +e encontrado antes do terraform import (deve falhar explicitamente)"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✅${NC} Não há set +e antes do terraform import (fail-fast correto)"
fi

# Verificar validação pós-import
check_pattern "$WORKFLOW_FILE" "terraform state show azurerm_resource_group.main" "Validação pós-import implementada"

# Verificar fail explícito se import falhar
check_pattern "$WORKFLOW_FILE" "ERRO: Import falhou" "Mensagem de erro se import falhar"
check_pattern "$WORKFLOW_FILE" "exit 1" "Falha explícita se import falhar"

echo ""

# ============================================
# Validações do Step: Terraform Plan
# ============================================
echo "=== Validações: Terraform Plan ==="

# Verificar verificação antes de gerar plan
check_pattern "$WORKFLOW_FILE" "Verificando sincronização do Resource Group antes de gerar plan" "Verificação antes de gerar plan"

# Verificar validação de inconsistência
check_pattern "$WORKFLOW_FILE" "ERRO CRÍTICO: Resource Group existe no Azure mas NÃO está no estado" "Validação de inconsistência no plan"

# Verificar fail explícito se inconsistência detectada
if grep -A 10 "ERRO CRÍTICO: Resource Group existe no Azure mas NÃO está no estado" "$WORKFLOW_FILE" | grep -q "exit 1"; then
    echo -e "${GREEN}✅${NC} Falha explícita se inconsistência detectada no plan"
else
    echo -e "${RED}❌${NC} Falta exit 1 após detectar inconsistência no plan"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# ============================================
# Validações do Step: Terraform Apply
# ============================================
echo "=== Validações: Terraform Apply ==="

# Verificar verificação do plan antes de aplicar
check_pattern "$WORKFLOW_FILE" "Plan tenta criar Resource Group" "Verificação se plan tenta criar Resource Group"

# Verificar validação de recurso existente
check_pattern "$WORKFLOW_FILE" "ERRO CRÍTICO: Plan tenta criar Resource Group que JÁ EXISTE no Azure" "Validação de recurso existente no apply"

# Verificar suporte a jq e fallback
check_pattern "$WORKFLOW_FILE" "command -v jq" "Suporte a jq implementado"
check_pattern "$WORKFLOW_FILE" "grep -q.*will be created" "Fallback com grep implementado"

# Verificar fail explícito se plan tentar criar existente
if grep -A 10 "ERRO CRÍTICO: Plan tenta criar Resource Group que JÁ EXISTE" "$WORKFLOW_FILE" | grep -q "exit 1"; then
    echo -e "${GREEN}✅${NC} Falha explícita se plan tentar criar recurso existente"
else
    echo -e "${RED}❌${NC} Falta exit 1 após detectar plan incorreto"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# ============================================
# Resumo
# ============================================
echo "=== Resumo da Validação ==="
echo ""

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ Todas as validações passaram!${NC}"
    echo -e "${GREEN}✅ Correções estão implementadas corretamente${NC}"
    echo ""
    echo "Próximos passos:"
    echo "  1. Testar o workflow em um ambiente de staging"
    echo "  2. Verificar logs do step 'Sync Existing Resources'"
    echo "  3. Confirmar que import funciona com variáveis explícitas"
    echo "  4. Validar que verificações falham corretamente quando necessário"
    exit 0
else
    echo -e "${RED}❌ Encontrados $ERRORS erro(s)${NC}"
    echo ""
    echo "Corrija os erros acima antes de considerar as correções validadas."
    exit 1
fi

