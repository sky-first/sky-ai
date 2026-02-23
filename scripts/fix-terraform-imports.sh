#!/bin/bash
# Script para importar recursos existentes no Azure para o Terraform
# Resolve os problemas de import faltante (Action Group) e conflito de IP público

set -euo pipefail

echo "=== Script de Correção de Imports do Terraform ==="
echo ""

# Variáveis
ENVIRONMENT="${1:-staging}"
SUBSCRIPTION_ID="${ARM_SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"
RESOURCE_GROUP_NAME="rg-ai-saas-${ENVIRONMENT}"

echo "Ambiente: $ENVIRONMENT"
echo "Subscription ID: $SUBSCRIPTION_ID"
echo "Resource Group: $RESOURCE_GROUP_NAME"
echo ""

# Verificar se está no diretório correto
if [ ! -f "main.tf" ] && [ ! -f "../main.tf" ]; then
    echo "ERRO: Execute este script do diretório infra/azure ou da raiz do projeto"
    exit 1
fi

# Navegar para o diretório do Terraform se necessário
if [ -f "../main.tf" ]; then
    cd ..
fi

TFVARS_FILE="terraform.tfvars.${ENVIRONMENT}"

if [ ! -f "$TFVARS_FILE" ]; then
    echo "ERRO: Arquivo $TFVARS_FILE não encontrado"
    exit 1
fi

# Nomes dos recursos
ACTION_GROUP_NAME="ai-saas-alerts-${ENVIRONMENT}"
NIC_NAME_EXPECTED="ai-saas-nic-${ENVIRONMENT}"
NIC_NAME_LEGACY="ai-saas-nic"
PIP_NAME="ai-saas-public-ip-${ENVIRONMENT}"

# IDs ARM
ACTION_GROUP_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP_NAME}/providers/Microsoft.Insights/actionGroups/${ACTION_GROUP_NAME}"

echo "=== 1. Importando Action Group ==="
if az monitor action-group show --resource-group "$RESOURCE_GROUP_NAME" --name "$ACTION_GROUP_NAME" --query id -o tsv > /dev/null 2>&1; then
    echo "Action Group existe no Azure: $ACTION_GROUP_NAME"
    
    if terraform state show azurerm_monitor_action_group.main > /dev/null 2>&1; then
        echo "[OK] Action Group já está no estado do Terraform"
    else
        echo "Importando Action Group..."
        terraform import \
            -var-file="$TFVARS_FILE" \
            -var="subscription_id=${SUBSCRIPTION_ID}" \
            azurerm_monitor_action_group.main "$ACTION_GROUP_ID"
        echo "[OK] Action Group importado com sucesso"
    fi
else
    echo "ℹ️  Action Group não existe no Azure: $ACTION_GROUP_NAME"
fi

echo ""
echo "=== 2. Verificando conflito de IP público com NIC antiga ==="

# Verificar se IP público existe e está associado a uma NIC
if az network public-ip show --resource-group "$RESOURCE_GROUP_NAME" --name "$PIP_NAME" --query id -o tsv > /dev/null 2>&1; then
    echo "IP público existe: $PIP_NAME"
    
    # Obter ID da configuração de IP associada
    IP_CONFIG_ID=$(az network public-ip show --resource-group "$RESOURCE_GROUP_NAME" --name "$PIP_NAME" --query "ipConfiguration.id" -o tsv 2>/dev/null || echo "")
    
    if [ -n "$IP_CONFIG_ID" ]; then
        # Extrair nome da NIC do ID
        CURRENT_NIC_NAME=$(echo "$IP_CONFIG_ID" | sed -n 's|.*/networkInterfaces/\([^/]*\)/ipConfigurations/.*|\1|p')
        
        # Antes de tentar desanexar, tente importar a NIC existente (evita o apply tentar criar outra NIC)
        if [ -n "$CURRENT_NIC_NAME" ]; then
            echo ""
            echo "=== 2.1. Importando NIC existente (se necessário) ==="
            NIC_ID=$(az network nic show --resource-group "$RESOURCE_GROUP_NAME" --name "$CURRENT_NIC_NAME" --query id -o tsv 2>/dev/null || echo "")
            if [ -n "$NIC_ID" ]; then
                if terraform state show azurerm_network_interface.main > /dev/null 2>&1; then
                    echo "[OK] NIC já está no estado do Terraform"
                else
                    echo "Importando NIC existente: $CURRENT_NIC_NAME"
                    terraform import \
                        -var-file="$TFVARS_FILE" \
                        -var="subscription_id=${SUBSCRIPTION_ID}" \
                        azurerm_network_interface.main "$NIC_ID" || true
                fi
            fi
        fi

        EXPECTED_NIC="$NIC_NAME_EXPECTED"
        if [ "$ENVIRONMENT" = "staging" ] && [ "$CURRENT_NIC_NAME" = "$NIC_NAME_LEGACY" ]; then
            EXPECTED_NIC="$NIC_NAME_LEGACY"
        fi

        if [ -n "$CURRENT_NIC_NAME" ] && [ "$CURRENT_NIC_NAME" != "$EXPECTED_NIC" ]; then
            echo "[WARNING] IP público está associado à NIC: $CURRENT_NIC_NAME (esperado: $EXPECTED_NIC)"
            echo "➡️  Desanexando IP público da NIC antiga..."
            
            # Tentar desanexar
            if az network nic ip-config update \
                --resource-group "$RESOURCE_GROUP_NAME" \
                --nic-name "$CURRENT_NIC_NAME" \
                --name "internal" \
                --remove public-ip-address 2>&1; then
                echo "[OK] IP público desanexado da NIC antiga: $CURRENT_NIC_NAME"
            else
                echo "[WARNING] Aviso: Não foi possível desanexar IP público"
                echo "   A NIC antiga pode estar em uso ou não existir mais"
            fi
        else
            echo "[OK] IP público está associado à NIC correta ou não está associado"
        fi
    else
        echo "[OK] IP público não está associado a nenhuma NIC"
    fi
else
    echo "ℹ️  IP público não existe no Azure: $PIP_NAME"
fi

echo ""
echo "=== 3. Verificando estado do Terraform ==="
terraform state list | grep -E "(azurerm_monitor_action_group.main|azurerm_network_interface.main)" || echo "Alguns recursos podem não estar no estado ainda"

echo ""
echo "[OK] Script de correção concluído!"
echo ""
echo "Próximos passos:"
echo "1. Execute: terraform plan -var-file=\"$TFVARS_FILE\" -var=\"subscription_id=${SUBSCRIPTION_ID}\""
echo "2. Verifique se não há mais erros de import"
echo "3. Execute: terraform apply (se o plan estiver OK)"

