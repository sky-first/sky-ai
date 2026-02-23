#!/bin/bash
# DEVOPS: Verifica acesso SSH e fornece alternativas (Bastion, Azure CLI, etc)

set -eu

VM_IP="${1:-20.86.142.1}"
VM_USER="${VM_USER:-azureuser}"
RESOURCE_GROUP="${RESOURCE_GROUP:-ai-saas-rg-poc-sky}"
VM_NAME="${VM_NAME:-ai-saas-vm-poc-sky}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "🔍 Verificando Acesso SSH à VM"
echo "==========================================${NC}"
echo ""

# 1. Testar SSH direto
echo -e "${BLUE}1.  Testando SSH direto (porta 22)...${NC}"
if timeout 5 bash -c "echo > /dev/tcp/$VM_IP/22" 2>/dev/null; then
    echo -e "${GREEN}[OK] Porta 22 está aberta${NC}"
    SSH_DIRECT=true
else
    echo -e "${RED}[ERROR] Porta 22 está fechada ou bloqueada${NC}"
    SSH_DIRECT=false
fi

echo ""

# 2. Verificar se Azure Bastion está configurado
echo -e "${BLUE}2.  Verificando Azure Bastion...${NC}"
if command -v az >/dev/null 2>&1; then
    if az account show >/dev/null 2>&1; then
        BASTION_NAME=$(az network bastion list -g "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null || echo "")
        if [ -n "$BASTION_NAME" ]; then
            echo -e "${GREEN}[OK] Azure Bastion encontrado: $BASTION_NAME${NC}"
            echo ""
            echo "[INFO] Use Azure Bastion para acessar a VM:"
            echo ""
            echo "   Via Portal Azure:"
            echo "   1. Acesse: https://portal.azure.com"
            echo "   2. Vá em: Virtual Machines > $VM_NAME"
            echo "   3. Clique em 'Connect' > 'Bastion'"
            echo ""
            echo "   Via Azure CLI:"
            echo "   az network bastion ssh \\"
            echo "     --name $BASTION_NAME \\"
            echo "     --resource-group $RESOURCE_GROUP \\"
            echo "     --target-resource-id /subscriptions/.../resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Compute/virtualMachines/$VM_NAME \\"
            echo "     --auth-type ssh \\"
            echo "     --username $VM_USER"
            echo ""
            BASTION_AVAILABLE=true
        else
            echo -e "${YELLOW}[WARNING] Azure Bastion não encontrado${NC}"
            BASTION_AVAILABLE=false
        fi
    else
        echo -e "${YELLOW}[WARNING] Não está logado no Azure CLI${NC}"
        echo "   Execute: az login"
        BASTION_AVAILABLE=false
    fi
else
    echo -e "${YELLOW}[WARNING] Azure CLI não instalado${NC}"
    BASTION_AVAILABLE=false
fi

echo ""

# 3. Verificar NSG (Network Security Group)
echo -e "${BLUE}3.  Verificando Network Security Group...${NC}"
if command -v az >/dev/null 2>&1 && az account show >/dev/null 2>&1; then
    NSG_NAME=$(az network nic list -g "$RESOURCE_GROUP" --query "[0].networkSecurityGroup.id" -o tsv 2>/dev/null | awk -F'/' '{print $NF}' || echo "")
    if [ -n "$NSG_NAME" ]; then
        echo "NSG: $NSG_NAME"
        SSH_RULE=$(az network nsg rule list -g "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" --query "[?destinationPortRange=='22']" -o json 2>/dev/null)
        if [ -n "$SSH_RULE" ] && [ "$SSH_RULE" != "[]" ]; then
            echo -e "${GREEN}[OK] Regra SSH (porta 22) encontrada no NSG${NC}"
        else
            echo -e "${RED}[ERROR] Regra SSH (porta 22) NÃO encontrada no NSG${NC}"
            echo ""
            echo "[INFO] Para abrir SSH, adicione regra no NSG:"
            echo "   az network nsg rule create \\"
            echo "     --resource-group $RESOURCE_GROUP \\"
            echo "     --nsg-name $NSG_NAME \\"
            echo "     --name AllowSSH \\"
            echo "     --priority 1000 \\"
            echo "     --direction Inbound \\"
            echo "     --access Allow \\"
            echo "     --protocol Tcp \\"
            echo "     --destination-port-ranges 22 \\"
            echo "     --source-address-prefixes 0.0.0.0/0"
        fi
    else
        echo -e "${YELLOW}[WARNING] NSG não encontrado${NC}"
    fi
else
    echo -e "${YELLOW}[WARNING] Azure CLI não disponível para verificar NSG${NC}"
fi

echo ""

# 4. Alternativa: Azure CLI run-command
echo -e "${BLUE}4.  Alternativa: Azure CLI run-command${NC}"
echo "Você pode executar comandos na VM sem SSH usando:"
echo ""
echo "   az vm run-command invoke \\"
echo "     -g $RESOURCE_GROUP \\"
echo "     -n $VM_NAME \\"
echo "     --command-id RunShellScript \\"
echo "     --scripts 'cd /home/azureuser/projeto/sky-poc-infra && bash scripts/azure/generate-self-signed-certs.sh . $VM_IP'"
echo ""

# 5. Resumo e recomendações
echo -e "${BLUE}=========================================="
echo "📋 Resumo e Recomendações"
echo "==========================================${NC}"
echo ""

if [ "$SSH_DIRECT" = "true" ]; then
    echo -e "${GREEN}[OK] SSH direto disponível${NC}"
    echo "   Use: ssh -i keys/azure/team/id_rsa_poc $VM_USER@$VM_IP"
elif [ "$BASTION_AVAILABLE" = "true" ]; then
    echo -e "${GREEN}[OK] Use Azure Bastion (recomendado)${NC}"
    echo "   Acesse via Portal Azure ou Azure CLI"
else
    echo -e "${YELLOW}[WARNING] SSH direto bloqueado e Bastion não disponível${NC}"
    echo ""
    echo "Opções:"
    echo "  1. Use Azure CLI run-command (veja acima)"
    echo "  2. Abra regra SSH no NSG (veja acima)"
    echo "  3. Configure Azure Bastion no Terraform"
fi

echo ""

