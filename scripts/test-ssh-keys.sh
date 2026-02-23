#!/bin/bash
# scripts/test-ssh-keys.sh
# Testa todas as chaves SSH disponíveis

set -euo pipefail

VM_IP="${VM_IP:-172.191.77.30}"
VM_USER="${VM_USER:-azureuser}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo " Testando chaves SSH para $VM_USER@$VM_IP"
echo ""

# Lista de chaves para testar
KEYS=(
    "$HOME/.ssh/id_ed25519"
    "$HOME/.ssh/id_rsa"
    "$PROJECT_DIR/keys/azure/team/id_rsa_poc"
    "$PROJECT_DIR/keys/azure/team/id_rsa_staging"
    "$PROJECT_DIR/keys/azure/team/id_rsa_dev"
    "$PROJECT_DIR/keys/azure/team/id_rsa_prod"
    "$PROJECT_DIR/keys/azure/id_rsa"
)

WORKING_KEY=""

for key in "${KEYS[@]}"; do
    if [ ! -f "$key" ]; then
        continue
    fi
    
    echo -n "Testando $key... "
    
    # Ajustar permissões se necessário
    chmod 600 "$key" 2>/dev/null || true
    
    if ssh -i "$key" \
        -o ConnectTimeout=5 \
        -o StrictHostKeyChecking=accept-new \
        -o BatchMode=yes \
        -o PasswordAuthentication=no \
        "$VM_USER@$VM_IP" "echo OK" 2>/dev/null | grep -q "OK"; then
        echo -e "${GREEN}[OK] FUNCIONA!${NC}"
        WORKING_KEY="$key"
        break
    else
        echo -e "${RED}[ERROR]${NC}"
    fi
done

echo ""

if [ -n "$WORKING_KEY" ]; then
    echo -e "${GREEN}[OK] Chave funcionando: $WORKING_KEY${NC}"
    echo ""
    echo "Para usar esta chave no deploy:"
    echo "  export SSH_KEY=\"$WORKING_KEY\""
    echo "  export VM_IP=$VM_IP"
    echo "  export BRANCH=staging"
    echo "  ./scripts/deploy-local-to-vm.sh"
    exit 0
else
    echo -e "${RED}[ERROR] Nenhuma chave funcionou${NC}"
    echo ""
    echo -e "${YELLOW}Possíveis causas:${NC}"
    echo "  1. Chave pública não está na VM (~/.ssh/authorized_keys)"
    echo "  2. VM não está rodando"
    echo "  3. Firewall/NSG bloqueando SSH"
    echo "  4. IP incorreto: $VM_IP"
    echo ""
    echo "Para adicionar sua chave pública na VM:"
    echo "  ssh-copy-id -i ~/.ssh/id_ed25519.pub $VM_USER@$VM_IP"
    exit 1
fi


