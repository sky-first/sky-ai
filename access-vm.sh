#!/bin/bash
# Script para acessar a VM Azure - Testa todas as opções

set -e

RESOURCE_GROUP="skyfirstlabs-poc"
VM_NAME="skyfirstlabs-staging"
VM_USER="azureuser"

# Tentar encontrar a chave SSH correta
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_KEY=""

# Lista de possíveis chaves (em ordem de prioridade)
POSSIBLE_KEYS=(
    "$SCRIPT_DIR/keys/azure/team/id_rsa_staging"
    "$SCRIPT_DIR/keys/azure/team/id_rsa_poc"
    "$SCRIPT_DIR/keys/azure/id_rsa"
    "$HOME/.ssh/id_rsa"
    "$HOME/.ssh/id_ed25519"
)

# Encontrar primeira chave que existe
for key in "${POSSIBLE_KEYS[@]}"; do
    if [ -f "$key" ]; then
        SSH_KEY="$key"
        break
    fi
done

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "🔐 Tentando Acessar VM Azure"
echo "==========================================${NC}"
echo ""

# Verificar Azure CLI
if ! command -v az >/dev/null 2>&1; then
    echo -e "${RED}❌ Azure CLI não encontrado${NC}"
    exit 1
fi

# Verificar login
if ! az account show >/dev/null 2>&1; then
    echo -e "${RED}❌ Não está logado no Azure CLI${NC}"
    echo "Execute: az login"
    exit 1
fi

# Obter informações da VM
echo -e "${BLUE}📋 Obtendo informações da VM...${NC}"
VM_ID=$(az vm show -g "$RESOURCE_GROUP" -n "$VM_NAME" --query id -o tsv 2>/dev/null || echo "")
PUBLIC_IP=$(az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" --query publicIps -o tsv 2>/dev/null || echo "")

if [ -z "$VM_ID" ]; then
    echo -e "${RED}❌ VM não encontrada${NC}"
    exit 1
fi

echo -e "${GREEN}✅ VM encontrada${NC}"
echo "   Resource Group: $RESOURCE_GROUP"
echo "   VM Name: $VM_NAME"
if [ -n "$PUBLIC_IP" ]; then
    echo "   Public IP: $PUBLIC_IP"
fi
echo ""

# Verificar Bastion
echo -e "${BLUE}🔍 Verificando Azure Bastion...${NC}"
BASTION_NAME=$(az network bastion list -g "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null || echo "")

if [ -n "$BASTION_NAME" ]; then
    echo -e "${GREEN}✅ Azure Bastion encontrado: $BASTION_NAME${NC}"
    echo ""
    echo -e "${YELLOW}Tentando conectar via Azure Bastion...${NC}"
    echo ""
    
    # Tentar conectar via Bastion
    if [ -n "$SSH_KEY" ] && [ -f "$SSH_KEY" ]; then
        echo -e "${GREEN}Usando chave: $SSH_KEY${NC}"
        echo ""
        echo "Comando: az network bastion ssh ..."
        echo ""
        az network bastion ssh \
            --name "$BASTION_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --target-resource-id "$VM_ID" \
            --auth-type ssh-key \
            --username "$VM_USER" \
            --ssh-key "$SSH_KEY" 2>/dev/null || {
                echo ""
                echo -e "${RED}❌ Falha ao conectar via Bastion (bug conhecido do Azure CLI)${NC}"
                echo ""
                
                # Tentar SSH direto como fallback
                if [ -n "$PUBLIC_IP" ] && [ -n "$SSH_KEY" ] && [ -f "$SSH_KEY" ]; then
                    echo -e "${YELLOW}🔄 Tentando SSH direto como alternativa...${NC}"
                    echo ""
                    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$VM_USER@$PUBLIC_IP" && exit 0 || {
                        echo ""
                        echo -e "${RED}❌ SSH direto também falhou${NC}"
                        echo ""
                    }
                fi
                
                echo -e "${YELLOW}💡 Possíveis causas:${NC}"
                echo "   1. Bug do Azure CLI Bastion (enableTunneling)"
                echo "   2. Porta SSH (22) pode estar fechada (Bastion habilitado)"
                echo "   3. Chave SSH incorreta"
                echo ""
                echo -e "${BLUE}Alternativa: Use Azure Portal${NC}"
                echo "   1. Acesse: https://portal.azure.com"
                echo "   2. Vá em: Virtual Machines > $VM_NAME"
                echo "   3. Clique em 'Connect' > 'Bastion'"
                echo "   4. Use a chave privada: $SSH_KEY"
                echo ""
                echo -e "${BLUE}Ou use Azure CLI run-command para comandos remotos:${NC}"
                echo "az vm run-command invoke \\"
                echo "  -g $RESOURCE_GROUP \\"
                echo "  -n $VM_NAME \\"
                echo "  --command-id RunShellScript \\"
                echo "  --scripts 'whoami && pwd'"
                echo ""
            }
    else
        echo -e "${RED}❌ Nenhuma chave SSH encontrada${NC}"
        echo ""
        echo "Chaves testadas:"
        for key in "${POSSIBLE_KEYS[@]}"; do
            if [ -f "$key" ]; then
                echo -e "  ${GREEN}✅ $key${NC}"
            else
                echo -e "  ${RED}❌ $key${NC}"
            fi
        done
        echo ""
        echo -e "${YELLOW}💡 Opções:${NC}"
        echo "   1. Use Azure Portal (não precisa de chave local):"
        echo "      https://portal.azure.com > Virtual Machines > $VM_NAME > Connect > Bastion"
        echo ""
        echo "   2. Ou adicione sua chave SSH em um dos caminhos acima"
    fi
else
    echo -e "${YELLOW}⚠️  Azure Bastion não encontrado${NC}"
    echo ""
    
    # Tentar SSH direto
    if [ -n "$PUBLIC_IP" ] && [ -n "$SSH_KEY" ] && [ -f "$SSH_KEY" ]; then
        echo -e "${BLUE}🔍 Tentando SSH direto...${NC}"
        echo ""
        ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$PUBLIC_IP" || {
            echo ""
            echo -e "${RED}❌ SSH direto falhou${NC}"
            echo ""
            echo -e "${YELLOW}💡 Use Azure CLI run-command como alternativa:${NC}"
            echo ""
            echo "az vm run-command invoke \\"
            echo "  -g $RESOURCE_GROUP \\"
            echo "  -n $VM_NAME \\"
            echo "  --command-id RunShellScript \\"
            echo "  --scripts 'whoami && pwd'"
        }
    else
        echo -e "${YELLOW}💡 Use Azure CLI run-command para executar comandos:${NC}"
        echo ""
        echo "az vm run-command invoke \\"
        echo "  -g $RESOURCE_GROUP \\"
        echo "  -n $VM_NAME \\"
        echo "  --command-id RunShellScript \\"
        echo "  --scripts 'whoami && pwd'"
        echo ""
        echo -e "${BLUE}Ou abra uma sessão interativa via Portal Azure:${NC}"
        echo "   1. Acesse: https://portal.azure.com"
        echo "   2. Vá em: Virtual Machines > $VM_NAME"
        echo "   3. Clique em 'Connect' > 'SSH' ou 'Bastion'"
    fi
fi

echo ""

