#!/bin/bash

# Script de verificação completa após deploy
# Verifica se tudo está funcionando corretamente

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

RESOURCE_GROUP="skyfirstlabs-poc"
VM_STAGING="skyfirstlabs-staging"
VM_PROD="skyfirstlabs-prod"

echo "=========================================="
echo -e "${CYAN}🔍 VERIFICAÇÃO COMPLETA DO DEPLOY${NC}"
echo "=========================================="
echo ""

ERRORS=0
WARNINGS=0

# Verificar Azure CLI
if ! command -v az &> /dev/null; then
    echo -e "${RED}❌${NC} Azure CLI não está instalado"
    echo "Instale: https://docs.microsoft.com/cli/azure/install-azure-cli"
    exit 1
fi

# Verificar login
if ! az account show &> /dev/null; then
    echo -e "${RED}❌${NC} Não está logado no Azure"
    echo "Execute: az login"
    exit 1
fi

SUBSCRIPTION=$(az account show --query "{name:name, id:id}" -o json)
echo -e "${BLUE}Subscription:${NC} $(echo $SUBSCRIPTION | jq -r '.name')"
echo -e "${BLUE}Subscription ID:${NC} $(echo $SUBSCRIPTION | jq -r '.id')"
echo ""

# 1. Verificar Resource Group
echo "=========================================="
echo "1️⃣ Resource Group"
echo "=========================================="
echo ""

if az group show --name "$RESOURCE_GROUP" --query id -o tsv &> /dev/null; then
    echo -e "${GREEN}✅${NC} Resource Group '$RESOURCE_GROUP' existe"
    LOC=$(az group show --name "$RESOURCE_GROUP" --query location -o tsv)
    echo -e "${CYAN}   Location:${NC} $LOC"
else
    echo -e "${RED}❌${NC} Resource Group '$RESOURCE_GROUP' não existe!"
    echo "Execute o deploy primeiro."
    ((ERRORS++))
    exit 1
fi

# 2. Verificar VMs
echo ""
echo "=========================================="
echo "2️⃣ Virtual Machines"
echo "=========================================="
echo ""

check_vm() {
    local vm_name=$1
    local env=$2
    
    if az vm show --resource-group "$RESOURCE_GROUP" --name "$vm_name" --query id -o tsv &> /dev/null; then
        echo -e "${GREEN}✅${NC} VM '$vm_name' existe"
        
        # Status
        STATUS=$(az vm show -d -g "$RESOURCE_GROUP" -n "$vm_name" --query powerState -o tsv)
        echo -e "${CYAN}   Status:${NC} $STATUS"
        
        if [ "$STATUS" = "VM running" ]; then
            # IP Público
            IP=$(az vm show -d -g "$RESOURCE_GROUP" -n "$vm_name" --query publicIps -o tsv)
            if [ -n "$IP" ]; then
                echo -e "${CYAN}   IP Público:${NC} $IP"
                
                # Testar conectividade HTTP
                echo -e "${CYAN}   Testando conectividade...${NC}"
                if timeout 5 curl -s -o /dev/null -w "%{http_code}" "http://$IP" 2>/dev/null | grep -q "200\|301\|302"; then
                    echo -e "${GREEN}   ✅ HTTP acessível${NC}"
                else
                    echo -e "${YELLOW}   ⚠️  HTTP não acessível (pode ser normal se ainda não houver aplicação)${NC}"
                    ((WARNINGS++))
                fi
            else
                echo -e "${YELLOW}   ⚠️  IP Público não encontrado${NC}"
                ((WARNINGS++))
            fi
        else
            echo -e "${YELLOW}   ⚠️  VM não está rodando!${NC}"
            echo -e "${CYAN}   Para iniciar:${NC} az vm start -g $RESOURCE_GROUP -n $vm_name"
            ((WARNINGS++))
        fi
        
        # Tamanho
        SIZE=$(az vm show -g "$RESOURCE_GROUP" -n "$vm_name" --query hardwareProfile.vmSize -o tsv)
        echo -e "${CYAN}   Tamanho:${NC} $SIZE"
        
        return 0
    else
        echo -e "${RED}❌${NC} VM '$vm_name' não existe!"
        ((ERRORS++))
        return 1
    fi
}

check_vm "$VM_STAGING" "staging"
echo ""
check_vm "$VM_PROD" "prod"

# 3. Verificar recursos de rede
echo ""
echo "=========================================="
echo "3️⃣ Recursos de Rede"
echo "=========================================="
echo ""

# VNets
VNETS=$(az network vnet list --resource-group "$RESOURCE_GROUP" --query "[].{Name:name, AddressSpace:addressSpace.addressPrefixes[0]}" -o table 2>/dev/null || echo "")
if [ -n "$VNETS" ] && [ "$VNETS" != "[]" ]; then
    echo -e "${GREEN}✅${NC} Virtual Networks encontradas:"
    echo "$VNETS" | sed 's/^/   /'
else
    echo -e "${YELLOW}⚠️${NC} Nenhuma Virtual Network encontrada"
    ((WARNINGS++))
fi

# NSGs
NSGS=$(az network nsg list --resource-group "$RESOURCE_GROUP" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$NSGS" ]; then
    echo ""
    echo -e "${GREEN}✅${NC} Network Security Groups encontradas:"
    for NSG in $NSGS; do
        echo -e "${CYAN}   - $NSG${NC}"
    done
else
    echo -e "${YELLOW}⚠️${NC} Nenhuma NSG encontrada"
    ((WARNINGS++))
fi

# Public IPs
PUBLIC_IPS=$(az network public-ip list --resource-group "$RESOURCE_GROUP" --query "[].{Name:name, IP:ipAddress}" -o table 2>/dev/null || echo "")
if [ -n "$PUBLIC_IPS" ] && [ "$PUBLIC_IPS" != "[]" ]; then
    echo ""
    echo -e "${GREEN}✅${NC} Public IPs encontradas:"
    echo "$PUBLIC_IPS" | sed 's/^/   /'
else
    echo -e "${YELLOW}⚠️${NC} Nenhuma Public IP encontrada"
    ((WARNINGS++))
fi

# 4. Verificar Terraform State (se disponível)
echo ""
echo "=========================================="
echo "4️⃣ Terraform State (opcional)"
echo "=========================================="
echo ""

if [ -d "infra/azure" ]; then
    cd infra/azure
    
    if terraform version &> /dev/null; then
        echo -e "${GREEN}✅${NC} Terraform disponível"
        
        # Verificar workspaces
        WORKSPACES=$(terraform workspace list 2>/dev/null || echo "")
        if [ -n "$WORKSPACES" ]; then
            echo ""
            echo -e "${CYAN}Workspaces disponíveis:${NC}"
            echo "$WORKSPACES" | sed 's/^/   /'
            
            # Verificar workspace staging
            if echo "$WORKSPACES" | grep -q "staging"; then
                echo ""
                echo -e "${CYAN}Verificando workspace staging...${NC}"
                terraform workspace select staging &> /dev/null || true
                if terraform state list 2>/dev/null | grep -q "azurerm_linux_virtual_machine.main"; then
                    echo -e "${GREEN}   ✅ VM staging no state${NC}"
                else
                    echo -e "${YELLOW}   ⚠️  VM staging não encontrada no state${NC}"
                    ((WARNINGS++))
                fi
            fi
            
            # Verificar workspace prod
            if echo "$WORKSPACES" | grep -q "prod"; then
                echo ""
                echo -e "${CYAN}Verificando workspace prod...${NC}"
                terraform workspace select prod &> /dev/null || true
                if terraform state list 2>/dev/null | grep -q "azurerm_linux_virtual_machine.main"; then
                    echo -e "${GREEN}   ✅ VM prod no state${NC}"
                else
                    echo -e "${YELLOW}   ⚠️  VM prod não encontrada no state${NC}"
                    ((WARNINGS++))
                fi
            fi
        else
            echo -e "${YELLOW}⚠️${NC} Terraform não inicializado ou sem workspaces"
            ((WARNINGS++))
        fi
    else
        echo -e "${YELLOW}⚠️${NC} Terraform não está instalado (opcional para esta verificação)"
    fi
    
    cd ../..
else
    echo -e "${YELLOW}⚠️${NC} Diretório infra/azure não encontrado"
fi

# 5. Resumo
echo ""
echo "=========================================="
echo -e "${CYAN}📊 RESUMO${NC}"
echo "=========================================="
echo ""

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ Deploy verificado com sucesso!${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}⚠️  $WARNINGS aviso(s) encontrado(s)${NC}"
        echo ""
        echo "Avisos não são críticos, mas devem ser revisados."
    fi
    echo ""
    echo -e "${GREEN}✅ Arquitetura funcionando corretamente!${NC}"
    echo ""
    echo "Próximos passos:"
    echo "1. Acessar VMs via SSH/Bastion"
    echo "2. Verificar aplicações rodando"
    echo "3. Monitorar custos no Azure Portal"
    exit 0
else
    echo -e "${RED}❌ Verificação falhou com $ERRORS erro(s)!${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}⚠️  $WARNINGS aviso(s) encontrado(s)${NC}"
    fi
    echo ""
    echo "Corrija os erros antes de considerar o deploy completo."
    exit 1
fi

