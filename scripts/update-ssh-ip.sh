#!/bin/bash
# scripts/update-ssh-ip.sh
# Atualiza automaticamente o IP SSH no terraform.tfvars.prod
# Útil quando seu IP público muda

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TFVARS_FILE="$PROJECT_DIR/infra/azure/terraform.tfvars.prod"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Atualizar IP SSH no Terraform                 ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════╝${NC}"
echo ""

# Descobrir IP atual
echo -e "${BLUE}Descobrindo seu IP público...${NC}"
IP=$(curl -s --max-time 5 https://api.ipify.org || curl -s --max-time 5 https://ifconfig.me/ip || curl -s --max-time 5 https://icanhazip.com)

if [ -z "$IP" ] || ! echo "$IP" | grep -qE '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'; then
    echo -e "${RED}❌ Erro: Não foi possível descobrir o IP público${NC}"
    echo -e "${YELLOW}Tente manualmente: curl https://api.ipify.org${NC}"
    exit 1
fi

echo -e "${GREEN}✅ IP encontrado: $IP${NC}"
echo ""

# Verificar IP atual no arquivo
CURRENT_IP=$(grep -E '^\s*"81\.84\.211\.111/32"|^\s*"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/32"' "$TFVARS_FILE" | head -1 | sed 's/.*"\([^"]*\)".*/\1/' | cut -d'/' -f1)

if [ -n "$CURRENT_IP" ] && [ "$CURRENT_IP" = "$IP" ]; then
    echo -e "${GREEN}✅ IP já está atualizado: $IP/32${NC}"
    exit 0
fi

# Mostrar IP atual no arquivo
if [ -n "$CURRENT_IP" ]; then
    echo -e "${YELLOW}IP atual no arquivo: $CURRENT_IP/32${NC}"
    echo -e "${YELLOW}Novo IP: $IP/32${NC}"
    echo ""
    read -p "Deseja atualizar? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo -e "${YELLOW}Atualização cancelada${NC}"
        exit 0
    fi
fi

# Backup do arquivo
BACKUP_FILE="${TFVARS_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$TFVARS_FILE" "$BACKUP_FILE"
echo -e "${BLUE}Backup criado: $BACKUP_FILE${NC}"

# Atualizar IP no arquivo
if grep -q '"81.84.211.111/32"' "$TFVARS_FILE"; then
    # Substituir IP específico conhecido
    sed -i.bak "s/\"81\.84\.211\.111\/32\"/\"$IP\/32\"/" "$TFVARS_FILE"
    rm -f "${TFVARS_FILE}.bak"
elif grep -qE '"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/32"' "$TFVARS_FILE"; then
    # Substituir qualquer IP/32 encontrado
    sed -i.bak "s/\"[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\/32\"/\"$IP\/32\"/" "$TFVARS_FILE"
    rm -f "${TFVARS_FILE}.bak"
else
    echo -e "${RED}❌ Erro: Não foi possível encontrar IP no arquivo${NC}"
    echo -e "${YELLOW}Atualize manualmente o arquivo: $TFVARS_FILE${NC}"
    exit 1
fi

echo -e "${GREEN}✅ IP atualizado para: $IP/32${NC}"
echo ""
echo -e "${CYAN}Próximos passos:${NC}"
echo -e "  1. Revisar mudanças: ${YELLOW}git diff $TFVARS_FILE${NC}"
echo -e "  2. Aplicar Terraform: ${YELLOW}cd infra/azure && terraform apply -var-file=terraform.tfvars.prod${NC}"
echo ""

