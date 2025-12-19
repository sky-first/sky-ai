#!/bin/bash

# Script de diagnóstico para VM do Azure
# Uso: ./scripts/azure/diagnose_azure_vm.sh

RESOURCE_GROUP="ai-saas-rg"
VM_NAME="ai-saas-vm"

echo "Diagnóstico da VM do Azure"
echo "================================"
echo ""

# 1. Verificar Azure CLI
echo "1⃣ Verificando Azure CLI..."
if command -v az &> /dev/null; then
    echo "Azure CLI instalado: $(az --version | head -1)"
else
    echo "Azure CLI não está instalado!"
    echo "Instale: brew install azure-cli"
    exit 1
fi

# 2. Verificar login
echo ""
echo "2⃣ Verificando login no Azure..."
if az account show &> /dev/null; then
    ACCOUNT=$(az account show --query "{name:name, subscriptionId:id}" -o json)
    echo "Logado no Azure"
    echo "Conta: $(echo $ACCOUNT | jq -r '.name')"
    echo "Subscription ID: $(echo $ACCOUNT | jq -r '.subscriptionId')"
else
    echo "Você não está logado no Azure!"
    echo "Execute: az login"
    exit 1
fi

# 3. Verificar Resource Group
echo ""
echo "3⃣ Verificando Resource Group..."
if az group show -n "$RESOURCE_GROUP" &> /dev/null; then
    echo "Resource Group '$RESOURCE_GROUP' existe"
    LOCATION=$(az group show -n "$RESOURCE_GROUP" --query location -o tsv)
    echo "Localização: $LOCATION"
else
    echo "Resource Group '$RESOURCE_GROUP' não existe!"
    echo "A infraestrutura ainda não foi criada."
    echo "Execute: cd infra/azure && terraform init && terraform apply"
    exit 1
fi

# 4. Verificar VM
echo ""
echo "4⃣ Verificando VM..."
VM_STATUS=$(az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" --query "powerState" -o tsv 2>/dev/null)

if [ -z "$VM_STATUS" ]; then
    echo "VM '$VM_NAME' não encontrada!"
    echo "A VM ainda não foi criada."
    echo "Execute: cd infra/azure && terraform apply"
    exit 1
else
    echo "VM '$VM_NAME' encontrada"
    echo "Status: $VM_STATUS"
    
    # Verificar se está rodando
    if [ "$VM_STATUS" != "VM running" ]; then
        echo "VM não está rodando!"
        echo "Inicie a VM: az vm start -g $RESOURCE_GROUP -n $VM_NAME"
    fi
fi

# 5. Obter IP público
echo ""
echo "5⃣ Verificando IP público..."
PUBLIC_IP=$(az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" --query publicIps -o tsv 2>/dev/null)

if [ -z "$PUBLIC_IP" ]; then
    echo "Não foi possível obter o IP público!"
else
    echo "IP público: $PUBLIC_IP"
fi

# 6. Verificar Network Security Group
echo ""
echo "6⃣ Verificando Network Security Group..."
NSG_NAME=$(az network nic list -g "$RESOURCE_GROUP" --query "[0].networkSecurityGroup.id" -o tsv | awk -F'/' '{print $NF}' 2>/dev/null)

if [ -n "$NSG_NAME" ]; then
    echo "NSG encontrado: $NSG_NAME"
    
    # Verificar regras SSH
    SSH_RULE=$(az network nsg rule list -g "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" --query "[?destinationPortRange=='22']" -o json 2>/dev/null)
    if [ -n "$SSH_RULE" ] && [ "$SSH_RULE" != "[]" ]; then
        echo "Regra SSH (porta 22) configurada"
    else
        echo "Regra SSH não encontrada!"
    fi
else
    echo "NSG não encontrado"
fi

# 7. Verificar chave SSH
echo ""
echo "7⃣ Verificando chave SSH local..."
# Caminho padrão para chave SSH da Azure (organizada em keys/azure/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_SSH_KEY="${SCRIPT_DIR}/../../keys/azure/id_rsa"
SSH_KEY_PATH="${SSH_KEY_PATH:-${DEFAULT_SSH_KEY}}"

if [ -f "$SSH_KEY_PATH" ]; then
    echo "Chave SSH encontrada: $SSH_KEY_PATH"
else
    echo "Chave SSH não encontrada em: $SSH_KEY_PATH"
    echo "Gere uma chave: ssh-keygen -t rsa -b 4096"
fi

# 8. Testar conectividade
echo ""
echo "8⃣ Testando conectividade..."
if [ -n "$PUBLIC_IP" ]; then
    if ping -c 1 -W 2 "$PUBLIC_IP" &> /dev/null; then
        echo "Ping bem-sucedido para $PUBLIC_IP"
    else
        echo "Ping falhou (isso é normal se o firewall bloquear ICMP)"
    fi
    
    # Testar porta SSH
    if timeout 3 bash -c "echo > /dev/tcp/$PUBLIC_IP/22" 2>/dev/null; then
        echo "Porta 22 (SSH) está acessível"
    else
        echo "Porta 22 (SSH) não está acessível"
        echo "Verifique o NSG e firewall"
    fi
fi

# Resumo
echo ""
echo "================================"
echo "Resumo"
echo "================================"

if [ "$VM_STATUS" == "VM running" ] && [ -n "$PUBLIC_IP" ]; then
    echo "VM está rodando e tem IP público"
    echo ""
    echo "Para conectar, execute:"
    echo "./access_server_azure.sh"
    echo ""
    echo "Ou manualmente:"
    if [ -f "$SSH_KEY_PATH" ]; then
        echo "ssh -i $SSH_KEY_PATH azureuser@$PUBLIC_IP"
    else
        echo "ssh azureuser@$PUBLIC_IP"
    fi
else
    echo "Há problemas que precisam ser resolvidos antes de conectar"
    echo ""
    if [ "$VM_STATUS" != "VM running" ]; then
        echo "Inicie a VM: az vm start -g $RESOURCE_GROUP -n $VM_NAME"
    fi
    if [ -z "$PUBLIC_IP" ]; then
        echo "Verifique se a infraestrutura foi criada: cd infra/azure && terraform apply"
    fi
fi
