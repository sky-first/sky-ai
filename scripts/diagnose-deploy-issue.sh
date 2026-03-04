#!/bin/bash

# Script de diagnóstico para identificar problemas no deploy
# Analisa configuração e identifica possíveis causas de erro

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=========================================="
echo -e "${CYAN}🔍 DIAGNÓSTICO DE PROBLEMAS NO DEPLOY${NC}"
echo "=========================================="
echo ""

ERRORS=0
WARNINGS=0
ISSUES=()

# 1. Verificar configurações dos tfvars
echo "1️⃣ Verificando configurações..."
echo ""

check_tfvars() {
    local env=$1
    local file="infra/azure/terraform.tfvars.$env"
    
    if [ ! -f "$file" ]; then
        echo -e "${RED}❌${NC} Arquivo não encontrado: $file"
        ((ERRORS++))
        return 1
    fi
    
    echo -e "${BLUE}Verificando $file:${NC}"
    
    # Resource Group
    RG=$(grep "^resource_group_name" "$file" | sed 's/.*= *"\([^"]*\)".*/\1/' | tr -d ' ' || echo "")
    if [ -z "$RG" ]; then
        echo -e "${RED}   ❌ resource_group_name não encontrado${NC}"
        ((ERRORS++))
        ISSUES+=("$env: resource_group_name não definido")
    else
        echo -e "${GREEN}   ✅ resource_group_name: $RG${NC}"
    fi
    
    # VM Name
    VM=$(grep "^vm_name" "$file" | sed 's/.*= *"\([^"]*\)".*/\1/' | tr -d ' ' || echo "")
    if [ -z "$VM" ]; then
        echo -e "${RED}   ❌ vm_name não encontrado${NC}"
        ((ERRORS++))
        ISSUES+=("$env: vm_name não definido")
    else
        echo -e "${GREEN}   ✅ vm_name: $VM${NC}"
    fi
    
    # Location
    LOC=$(grep "^location" "$file" | sed 's/.*= *"\([^"]*\)".*/\1/' | tr -d ' ' || echo "")
    if [ -z "$LOC" ]; then
        echo -e "${YELLOW}   ⚠️  location não encontrado (usará default)${NC}"
        ((WARNINGS++))
    else
        echo -e "${GREEN}   ✅ location: $LOC${NC}"
    fi
    
    # Verificar se staging e prod usam mesmo Resource Group
    if [ "$env" = "prod" ] && [ -n "$RG" ]; then
        STAGING_RG=$(grep "^resource_group_name" "infra/azure/terraform.tfvars.staging" | sed 's/.*= *"\([^"]*\)".*/\1/' | tr -d ' ' || echo "")
        if [ "$RG" != "$STAGING_RG" ]; then
            echo -e "${YELLOW}   ⚠️  Resource Group diferente de staging!${NC}"
            echo -e "${YELLOW}      Staging: $STAGING_RG${NC}"
            echo -e "${YELLOW}      Prod: $RG${NC}"
            ((WARNINGS++))
            ISSUES+=("Resource Groups diferentes entre staging e prod")
        else
            echo -e "${GREEN}   ✅ Resource Group compartilhado: $RG${NC}"
        fi
    fi
    
    echo ""
}

check_tfvars "staging"
check_tfvars "prod"

# 2. Verificar main.tf
echo "2️⃣ Verificando main.tf..."
echo ""

if grep -q "ignore_changes = \[tags\]" infra/azure/main.tf; then
    echo -e "${GREEN}✅${NC} lifecycle ignore_changes configurado no Resource Group"
else
    echo -e "${YELLOW}⚠️${NC} lifecycle ignore_changes não encontrado (pode causar conflitos)"
    ((WARNINGS++))
    ISSUES+=("lifecycle ignore_changes não configurado")
fi

if grep -q "compartilhado entre múltiplos ambientes" infra/azure/main.tf; then
    echo -e "${GREEN}✅${NC} Comentário sobre Resource Group compartilhado presente"
else
    echo -e "${YELLOW}⚠️${NC} Comentário sobre Resource Group compartilhado não encontrado"
fi

echo ""

# 3. Verificar possíveis problemas conhecidos
echo "3️⃣ Verificando problemas conhecidos..."
echo ""

# Problema 1: Resource Group existe mas Terraform tenta criar
echo -e "${BLUE}Problema comum 1: Resource Group já existe mas Terraform tenta criar${NC}"
echo "   Causa: Resource Group existe no Azure mas não está no estado do Terraform"
echo "   Solução: O workflow tem step 'Sync Existing Resources' que deve importar"
echo "   Verificar: Logs do step 'Sync Existing Resources' no GitHub Actions"
echo ""

# Problema 2: Workspace incorreto
echo -e "${BLUE}Problema comum 2: Workspace incorreto${NC}"
echo "   Causa: Workspace staging/prod não selecionado corretamente"
echo "   Solução: Workflow deve selecionar workspace baseado no ambiente"
echo "   Verificar: Logs do step 'Select Workspace' no GitHub Actions"
echo ""

# Problema 3: Variáveis não passadas corretamente
echo -e "${BLUE}Problema comum 3: Variáveis não passadas no terraform import${NC}"
echo "   Causa: terraform import precisa de todas as variáveis do tfvars"
echo "   Solução: Workflow passa -var-file e -var explicitamente"
echo "   Verificar: Logs do step 'Sync Existing Resources' - comando terraform import"
echo ""

# Problema 4: Backend não configurado
echo -e "${BLUE}Problema comum 4: Backend do Terraform não configurado${NC}"
echo "   Causa: Terraform não consegue salvar estado no backend remoto"
echo "   Solução: Verificar secrets TF_BACKEND_* no GitHub"
echo "   Verificar: Logs do step 'Terraform Init' no GitHub Actions"
echo ""

# 4. Verificar workflow
echo "4️⃣ Verificando workflow deploy.yml..."
echo ""

if grep -q "Sync Existing Resources with Terraform State" .github/workflows/deploy.yml; then
    echo -e "${GREEN}✅${NC} Step 'Sync Existing Resources' encontrado no workflow"
else
    echo -e "${RED}❌${NC} Step 'Sync Existing Resources' NÃO encontrado!"
    ((ERRORS++))
    ISSUES+=("Step Sync Existing Resources não encontrado no workflow")
fi

if grep -q "terraform import.*azurerm_resource_group.main" .github/workflows/deploy.yml; then
    echo -e "${GREEN}✅${NC} Comando terraform import para Resource Group encontrado"
else
    echo -e "${YELLOW}⚠️${NC} Comando terraform import não encontrado explicitamente"
    ((WARNINGS++))
fi

echo ""

# 5. Resumo e recomendações
echo "=========================================="
echo -e "${CYAN}📊 RESUMO${NC}"
echo "=========================================="
echo ""

if [ ${#ISSUES[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠️  Problemas identificados:${NC}"
    for issue in "${ISSUES[@]}"; do
        echo "   - $issue"
    done
    echo ""
fi

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ Configuração parece correta!${NC}"
    echo ""
    echo "Se ainda há erros no GitHub Actions, verifique:"
    echo "1. Logs do step 'Sync Existing Resources'"
    echo "2. Logs do step 'Terraform Plan'"
    echo "3. Se Resource Group existe no Azure: az group show --name skyfirstlabs-poc"
    echo "4. Se workspace está correto: terraform workspace show"
    echo ""
    echo "Possíveis causas de erro:"
    echo "- Resource Group existe mas import falhou silenciosamente"
    echo "- Workspace incorreto (staging vs prod)"
    echo "- Backend do Terraform não configurado corretamente"
    echo "- Variáveis não passadas corretamente no terraform import"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Configuração tem avisos, mas pode funcionar${NC}"
    echo ""
    echo "Recomendações:"
    for issue in "${ISSUES[@]}"; do
        echo "   - Corrigir: $issue"
    done
    exit 0
else
    echo -e "${RED}❌ Configuração tem erros que precisam ser corrigidos!${NC}"
    echo ""
    echo "Erros encontrados:"
    for issue in "${ISSUES[@]}"; do
        echo "   - $issue"
    done
    exit 1
fi

