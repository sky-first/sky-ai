#!/bin/bash
# scripts/setup-post-deploy.sh
# Script para configurar acesso público após deploy na VM
# Deve ser executado APÓS o terraform apply

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$PROJECT_DIR/infra/azure"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🌐 Configurando acesso público após deploy...${NC}"
echo ""

# 1. Obter IP público
echo -e "${BLUE}1. Obtendo IP público da VM...${NC}"
cd "$TF_DIR"

VM_IP=$(terraform output -raw vm_public_ip 2>/dev/null || echo "")

if [ -z "$VM_IP" ]; then
  echo -e "${RED}❌ Não foi possível obter IP da VM${NC}"
  echo -e "${YELLOW}   Verifique se o deploy foi concluído${NC}"
  exit 1
fi

echo -e "${GREEN}✅ IP Público: $VM_IP${NC}"

# 2. Testar conectividade
echo ""
echo -e "${BLUE}2. Testando conectividade...${NC}"
if curl -s --connect-timeout 5 "http://$VM_IP" > /dev/null 2>&1; then
  echo -e "${GREEN}✅ VM está acessível${NC}"
else
  echo -e "${YELLOW}⚠️  VM pode não estar totalmente pronta ainda${NC}"
  echo -e "${YELLOW}   Aguarde alguns minutos e tente novamente${NC}"
fi

# 3. Acessar VM e configurar
echo ""
echo -e "${BLUE}3. Configurando .env na VM...${NC}"
echo -e "${YELLOW}   Você precisará acessar a VM via SSH${NC}"
echo ""
echo -e "${BLUE}Comandos para executar na VM:${NC}"
echo ""
echo -e "${YELLOW}ssh azureuser@$VM_IP${NC}"
echo ""
echo -e "${BLUE}Depois, na VM, execute:${NC}"
echo ""
cat << 'EOF'
cd ~/projeto/sky-poc-infra

# Obter IP (se necessário)
VM_IP="<IP_DA_VM>"

# Atualizar NEXT_PUBLIC_API_URL no .env
if [ -f .env ]; then
  # Atualizar ou adicionar
  if grep -q "NEXT_PUBLIC_API_URL" .env; then
    sed -i "s|NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=http://$VM_IP/api/v1|" .env
  else
    echo "NEXT_PUBLIC_API_URL=http://$VM_IP/api/v1" >> .env
  fi
  
  # Reiniciar frontend
  docker compose restart frontend
  
  echo "✅ Configurado!"
else
  echo "⚠️  Arquivo .env não encontrado"
  echo "   Crie a partir de env.example ou configure via Key Vault"
fi
EOF

echo ""
echo -e "${GREEN}✅ URLs de Acesso:${NC}"
echo ""
echo -e "  Frontend: ${YELLOW}http://$VM_IP${NC}"
echo -e "  API: ${YELLOW}http://$VM_IP/api/${NC}"
echo -e "  Health: ${YELLOW}http://$VM_IP/api/health${NC}"
echo ""
echo -e "${BLUE}📋 Compartilhe com o time:${NC}"
echo -e "   ${YELLOW}Aplicação disponível em: http://$VM_IP${NC}"
echo ""

