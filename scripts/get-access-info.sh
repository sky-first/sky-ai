#!/bin/bash
# scripts/get-access-info.sh
# Script para obter informações de acesso após deploy no GitHub Actions

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$PROJECT_DIR/infra/azure"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   📍 Informações de Acesso - Aplicação Deployada${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Verificar se está no diretório correto
if [ ! -d "$TF_DIR" ]; then
  echo -e "${RED}[ERROR] Diretório Terraform não encontrado: $TF_DIR${NC}"
  echo -e "${YELLOW}   Execute este script do diretório raiz do projeto${NC}"
  exit 1
fi

# Obter IP público
echo -e "${BLUE}🔍 Obtendo IP público da VM...${NC}"
cd "$TF_DIR"

# Verificar se o Terraform está inicializado
if [ ! -f ".terraform/terraform.tfstate" ] && [ ! -f "terraform.tfstate" ]; then
  echo -e "${YELLOW}[WARNING] Estado do Terraform não encontrado localmente${NC}"
  echo ""
  echo -e "${BLUE}Opções para obter o IP:${NC}"
  echo ""
  echo -e "1. ${CYAN}Via GitHub Actions (Recomendado):${NC}"
  echo -e "   - Acesse: https://github.com/sky-first/sky-poc-infra/actions"
  echo -e "   - Abra o último workflow executado"
  echo -e "   - Procure pela seção 'Show Terraform Outputs'"
  echo -e "   - O IP estará em 'vm_public_ip'"
  echo ""
  echo -e "2. ${CYAN}Via Azure Portal:${NC}"
  echo -e "   - Acesse: https://portal.azure.com"
  echo -e "   - Vá em 'Resource Groups' > 'ai-saas-rg-<ambiente>'"
  echo -e "   - Procure pelo recurso 'Public IP'"
  echo ""
  echo -e "3. ${CYAN}Via Azure CLI:${NC}"
  echo -e "   az vm show -d -g <resource-group> -n <vm-name> --query publicIps -o tsv"
  echo ""
  exit 0
fi

# Tentar obter o IP do Terraform
VM_IP=$(terraform output -raw vm_public_ip 2>/dev/null || echo "")

if [ -z "$VM_IP" ]; then
  echo -e "${YELLOW}[WARNING] Não foi possível obter IP do Terraform local${NC}"
  echo ""
  echo -e "${BLUE}[INFO] Como obter o IP:${NC}"
  echo ""
  echo -e "${CYAN}Opção 1: GitHub Actions${NC}"
  echo -e "   1. Acesse: https://github.com/sky-first/sky-poc-infra/actions"
  echo -e "   2. Abra o último workflow 'Deploy Infrastructure'"
  echo -e "   3. Procure pela seção 'Show Terraform Outputs'"
  echo -e "   4. Copie o valor de 'vm_public_ip'"
  echo ""
  echo -e "${CYAN}Opção 2: Azure Portal${NC}"
  echo -e "   1. Acesse: https://portal.azure.com"
  echo -e "   2. Resource Groups > ai-saas-rg-<ambiente>"
  echo -e "   3. Public IP addresses > ai-saas-public-ip-<ambiente>"
  echo ""
  echo -e "${CYAN}Opção 3: Azure CLI${NC}"
  echo -e "   az network public-ip list -g <resource-group> --query '[].ipAddress' -o tsv"
  echo ""
  exit 0
fi

echo -e "${GREEN}[OK] IP Público encontrado: ${CYAN}$VM_IP${NC}"
echo ""

# Testar conectividade
echo -e "${BLUE}🔗 Testando conectividade...${NC}"
if curl -s --connect-timeout 5 "http://$VM_IP" > /dev/null 2>&1; then
  echo -e "${GREEN}[OK] VM está acessível!${NC}"
else
  echo -e "${YELLOW}[WARNING] VM pode não estar totalmente pronta ainda${NC}"
  echo -e "${YELLOW}   Aguarde alguns minutos após o deploy${NC}"
fi
echo ""

# Mostrar URLs de acesso
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}🌐 URLs de Acesso:${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${YELLOW}Frontend:${NC}  ${CYAN}http://$VM_IP${NC}"
echo -e "  ${YELLOW}API:${NC}       ${CYAN}http://$VM_IP/api/v1${NC}"
echo -e "  ${YELLOW}Health:${NC}    ${CYAN}http://$VM_IP/api/v1/health${NC}"
echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}📋 Informações Adicionais:${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${YELLOW}SSH:${NC}       ${CYAN}ssh azureuser@$VM_IP${NC}"
echo -e "  ${YELLOW}PostgreSQL:${NC} ${CYAN}$VM_IP:5433${NC}"
echo ""
echo -e "${BLUE}[INFO] Dica:${NC} Copie e cole as URLs acima no navegador para acessar!"
echo ""

