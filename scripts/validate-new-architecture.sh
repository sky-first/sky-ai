#!/bin/bash

# Script de validação da nova arquitetura
# Verifica se tudo está configurado corretamente antes do deploy

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo "=========================================="
echo -e "${CYAN} VALIDAÇÃO DA NOVA ARQUITETURA${NC}"
echo "=========================================="
echo ""

ERRORS=0
WARNINGS=0

# Função para verificar arquivo
check_file() {
    local file=$1
    local description=$2
    
    if [ -f "$file" ]; then
        echo -e "${GREEN}[OK]${NC} $description: $file"
        return 0
    else
        echo -e "${RED}[ERROR]${NC} $description não encontrado: $file"
        ((ERRORS++))
        return 1
    fi
}

# Função para verificar conteúdo em arquivo
check_content() {
    local file=$1
    local pattern=$2
    local description=$3
    
    if grep -q "$pattern" "$file" 2>/dev/null; then
        echo -e "${GREEN}[OK]${NC} $description"
        return 0
    else
        echo -e "${RED}[ERROR]${NC} $description não encontrado em $file"
        ((ERRORS++))
        return 1
    fi
}

echo "1. Verificando arquivos de configuração..."
echo ""

# Verificar arquivos principais
check_file "infra/azure/terraform.tfvars.staging" "terraform.tfvars.staging"
check_file "infra/azure/terraform.tfvars.prod" "terraform.tfvars.prod"
check_file "infra/azure/main.tf" "main.tf"
check_file "docs/PROXIMOS-PASSOS-NOVA-ARQUITETURA.md" "Documentação"

echo ""
echo "2. Verificando configurações..."
echo ""

# Verificar resource_group_name em staging
if check_content "infra/azure/terraform.tfvars.staging" "resource_group_name = \"skyfirstlabs-poc\"" "Resource Group staging = skyfirstlabs-poc"; then
    :
fi

# Verificar vm_name em staging
if check_content "infra/azure/terraform.tfvars.staging" "vm_name.*=.*\"skyfirstlabs-staging\"" "VM staging = skyfirstlabs-staging"; then
    :
fi

# Verificar resource_group_name em prod
if check_content "infra/azure/terraform.tfvars.prod" "resource_group_name = \"skyfirstlabs-poc\"" "Resource Group prod = skyfirstlabs-poc"; then
    :
fi

# Verificar vm_name em prod
if check_content "infra/azure/terraform.tfvars.prod" "vm_name.*=.*\"skyfirstlabs-prod\"" "VM prod = skyfirstlabs-prod"; then
    :
fi

# Verificar location (deve ser igual em ambos)
STAGING_LOC=$(grep "^location" infra/azure/terraform.tfvars.staging | sed 's/.*= *"\([^"]*\)".*/\1/' | tr -d ' ')
PROD_LOC=$(grep "^location" infra/azure/terraform.tfvars.prod | sed 's/.*= *"\([^"]*\)".*/\1/' | tr -d ' ')

if [ "$STAGING_LOC" = "$PROD_LOC" ] && [ -n "$STAGING_LOC" ]; then
    echo -e "${GREEN}[OK]${NC} Location igual em ambos: $STAGING_LOC"
else
    echo -e "${RED}[ERROR]${NC} Location diferente ou vazio! Staging: $STAGING_LOC, Prod: $PROD_LOC"
    ((ERRORS++))
fi

echo ""
echo "3. Verificando main.tf..."
echo ""

# Verificar lifecycle ignore_changes no Resource Group
if check_content "infra/azure/main.tf" "ignore_changes = \[tags\]" "Lifecycle ignore_changes no Resource Group"; then
    :
fi

# Verificar comentário sobre Resource Group compartilhado
if check_content "infra/azure/main.tf" "compartilhado entre múltiplos ambientes" "Comentário sobre Resource Group compartilhado"; then
    :
fi

echo ""
echo "4. Verificando Azure CLI (se disponível)..."
echo ""

if command -v az &> /dev/null; then
    echo -e "${GREEN}[OK]${NC} Azure CLI instalado"
    
    # Verificar login
    if az account show &> /dev/null; then
        echo -e "${GREEN}[OK]${NC} Logado no Azure"
        
        SUBSCRIPTION=$(az account show --query "{name:name, id:id}" -o json 2>/dev/null || echo "{}")
        echo -e "${CYAN}   Subscription:${NC} $(echo $SUBSCRIPTION | jq -r '.name // "N/A"')"
        
        echo ""
        echo "5. Verificando estado atual no Azure..."
        echo ""
        
        # Verificar Resource Group
        if az group show --name skyfirstlabs-poc --query id -o tsv &> /dev/null; then
            echo -e "${YELLOW}[WARNING]${NC} Resource Group 'skyfirstlabs-poc' já existe no Azure"
            LOC=$(az group show --name skyfirstlabs-poc --query location -o tsv)
            echo -e "${CYAN}   Location:${NC} $LOC"
            ((WARNINGS++))
        else
            echo -e "${GREEN}[OK]${NC} Resource Group 'skyfirstlabs-poc' não existe (será criado no primeiro deploy)"
        fi
        
        # Verificar VMs
        VMS=$(az vm list --resource-group skyfirstlabs-poc --query "[].{Name:name, Status:powerState}" -o table 2>/dev/null || echo "")
        if [ -n "$VMS" ] && [ "$VMS" != "[]" ]; then
            echo -e "${YELLOW}[WARNING]${NC} VMs encontradas no Resource Group skyfirstlabs-poc:"
            echo "$VMS" | sed 's/^/   /'
            ((WARNINGS++))
        else
            echo -e "${GREEN}[OK]${NC} Nenhuma VM encontrada no Resource Group skyfirstlabs-poc (serão criadas no deploy)"
        fi
        
        # Verificar Resource Groups antigos
        echo ""
        echo "6. Verificando Resource Groups antigos..."
        echo ""
        
        OLD_RGS=("rg-ai-saas-staging" "rg-ai-saas-prod")
        for RG in "${OLD_RGS[@]}"; do
            if az group show --name "$RG" --query id -o tsv &> /dev/null; then
                echo -e "${YELLOW}[WARNING]${NC} Resource Group antigo encontrado: $RG"
                VMS_OLD=$(az vm list --resource-group "$RG" --query "[].name" -o tsv 2>/dev/null || echo "")
                if [ -n "$VMS_OLD" ]; then
                    echo -e "${CYAN}   VMs:${NC} $VMS_OLD"
                    echo -e "${YELLOW}   Ação recomendada:${NC} Mover VMs para skyfirstlabs-poc ou remover Resource Group antigo"
                fi
                ((WARNINGS++))
            fi
        done
        
    else
        echo -e "${YELLOW}[WARNING]${NC} Não está logado no Azure. Execute: az login"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}[WARNING]${NC} Azure CLI não instalado (opcional para validação local)"
    ((WARNINGS++))
fi

echo ""
echo "=========================================="
echo -e "${CYAN} RESUMO${NC}"
echo "=========================================="
echo ""

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}[OK] Validação concluída sem erros!${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}[WARNING] $WARNINGS aviso(s) encontrado(s)${NC}"
    fi
    echo ""
    echo "Próximos passos:"
    echo "1. Fazer push para staging: git push origin staging"
    echo "2. Monitorar deploy no GitHub Actions"
    echo "3. Após staging, fazer push para main: git push origin main"
    exit 0
else
    echo -e "${RED}[ERROR] Validação falhou com $ERRORS erro(s)!${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}[WARNING] $WARNINGS aviso(s) encontrado(s)${NC}"
    fi
    echo ""
    echo "Corrija os erros antes de fazer deploy."
    exit 1
fi

