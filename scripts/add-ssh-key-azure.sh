#!/bin/bash
# scripts/add-ssh-key-azure.sh
# Adiciona chave SSH na VM Azure usando Azure CLI

set -euo pipefail

VM_IP="${VM_IP:-172.191.77.30}"
VM_USER="${VM_USER:-azureuser}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔑 Adicionando chave SSH na VM Azure${NC}"
echo ""

# Encontrar Azure CLI
AZ_CLI=""
for path in /usr/local/bin/az /opt/homebrew/bin/az "$HOME/.azure/bin/az" "$(which az 2>/dev/null)"; do
    if [ -x "$path" ] 2>/dev/null; then
        AZ_CLI="$path"
        break
    fi
done

if [ -z "$AZ_CLI" ]; then
    echo -e "${RED}[ERROR] Azure CLI não encontrado${NC}"
    echo ""
    echo "Instale o Azure CLI:"
    echo "  brew install azure-cli"
    echo ""
    echo "Ou use o método manual:"
    echo "  1. Acesse a VM via Azure Portal (Bastion ou Serial Console)"
    echo "  2. Execute: echo '$(cat ~/.ssh/id_ed25519.pub)' >> ~/.ssh/authorized_keys"
    exit 1
fi

echo -e "${GREEN}[OK] Azure CLI encontrado: $AZ_CLI${NC}"
echo ""

# Verificar login
echo "Verificando login Azure..."
if ! $AZ_CLI account show &>/dev/null; then
    echo -e "${RED}[ERROR] Não está logado no Azure CLI${NC}"
    echo ""
    echo "Execute: az login"
    exit 1
fi

echo -e "${GREEN}[OK] Logado no Azure${NC}"
echo ""

# Ler chave pública
SSH_PUB_KEY_FILE="$HOME/.ssh/id_ed25519.pub"
if [ ! -f "$SSH_PUB_KEY_FILE" ]; then
    echo -e "${RED}[ERROR] Chave pública não encontrada: $SSH_PUB_KEY_FILE${NC}"
    exit 1
fi

SSH_PUB_KEY=$(cat "$SSH_PUB_KEY_FILE")
echo -e "${BLUE}Chave pública:${NC}"
echo "$SSH_PUB_KEY"
echo ""

# Encontrar VM pelo IP
echo "Procurando VM com IP $VM_IP..."
VM_INFO=$($AZ_CLI vm list-ip-addresses --query "[?virtualMachine.network.publicIpAddresses[?ipAddress=='$VM_IP'] || virtualMachine.network.privateIpAddresses[?ipAddress=='$VM_IP']].{Name:virtualMachine.name, ResourceGroup:virtualMachine.resourceGroup}" -o tsv 2>/dev/null || echo "")

if [ -z "$VM_INFO" ]; then
    echo -e "${YELLOW}[WARNING] VM não encontrada pelo IP. Listando todas as VMs...${NC}"
    echo ""
    $AZ_CLI vm list --query "[].{Name:name, ResourceGroup:resourceGroup, PublicIP:publicIps}" -o table
    echo ""
    echo "Por favor, informe:"
    read -p "Nome da VM: " VM_NAME
    read -p "Resource Group: " VM_RG
else
    VM_NAME=$(echo "$VM_INFO" | cut -f1)
    VM_RG=$(echo "$VM_INFO" | cut -f2)
    echo -e "${GREEN}[OK] VM encontrada: $VM_NAME (RG: $VM_RG)${NC}"
fi

echo ""
echo "Adicionando chave SSH na VM..."
echo "  VM: $VM_NAME"
echo "  Resource Group: $VM_RG"
echo "  Usuário: $VM_USER"
echo ""

# Adicionar chave SSH
if $AZ_CLI vm user update \
    --resource-group "$VM_RG" \
    --name "$VM_NAME" \
    --username "$VM_USER" \
    --ssh-key-value "$SSH_PUB_KEY" 2>&1; then
    echo ""
    echo -e "${GREEN}[OK] Chave SSH adicionada com sucesso!${NC}"
    echo ""
    echo "Testando conexão..."
    sleep 2
    
    if ssh -i ~/.ssh/id_ed25519 -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "$VM_USER@$VM_IP" "echo 'OK'" 2>&1 | grep -q "OK"; then
        echo -e "${GREEN}[OK] Conexão SSH funcionando!${NC}"
        echo ""
        echo "Agora você pode executar o deploy:"
        echo "  export VM_IP=$VM_IP"
        echo "  export BRANCH=staging"
        echo "  export SSH_KEY=~/.ssh/id_ed25519"
        echo "  ./scripts/deploy-local-to-vm.sh"
    else
        echo -e "${YELLOW}[WARNING] Chave adicionada, mas conexão ainda não funciona${NC}"
        echo "Aguarde alguns segundos e tente novamente."
    fi
else
    echo -e "${RED}[ERROR] Erro ao adicionar chave SSH${NC}"
    exit 1
fi


