#!/bin/bash
# DEVOPS: Configura HTTPS na VM usando Azure CLI run-command (sem SSH direto)
# Útil quando Azure Bastion está habilitado ou SSH está bloqueado

set -eu

VM_IP="${1:-20.86.142.1}"
RESOURCE_GROUP="${RESOURCE_GROUP:-POC-SKY}"
VM_NAME="${VM_NAME:-poc-sky}"
PROJECT_DIR="${PROJECT_DIR:-/home/azureuser/projeto/sky-poc-infra}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "🔐 Configurando HTTPS na VM (Azure CLI)"
echo "==========================================${NC}"
echo ""
echo "VM: $VM_NAME"
echo "Resource Group: $RESOURCE_GROUP"
echo "IP: $VM_IP"
echo ""

# Verificar Azure CLI
if ! command -v az >/dev/null 2>&1; then
    echo -e "${RED}❌ Azure CLI não encontrado${NC}"
    echo "Instale: https://aka.ms/InstallAzureCLI"
    exit 1
fi

# Verificar login
if ! az account show >/dev/null 2>&1; then
    echo -e "${RED}❌ Não está logado no Azure CLI${NC}"
    echo "Execute: az login"
    exit 1
fi

echo -e "${GREEN}✅ Azure CLI OK${NC}"
echo ""

# Passo 1: Gerar certificados
echo -e "${BLUE}1️⃣  Gerando certificados SSL auto-assinados...${NC}"
az vm run-command invoke \
    -g "$RESOURCE_GROUP" \
    -n "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "cd $PROJECT_DIR && bash scripts/azure/generate-self-signed-certs.sh . $VM_IP" \
    --output json | jq -r '.value[0].message' || {
    echo -e "${RED}❌ Erro ao gerar certificados${NC}"
    exit 1
}

echo -e "${GREEN}✅ Certificados gerados${NC}"
echo ""

# Passo 2: Aplicar configuração Nginx
echo -e "${BLUE}2️⃣  Aplicando configuração Nginx (HTTPS)...${NC}"
az vm run-command invoke \
    -g "$RESOURCE_GROUP" \
    -n "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "cd $PROJECT_DIR && bash scripts/azure/apply-nginx-config.sh ." \
    --output json | jq -r '.value[0].message' || {
    echo -e "${RED}❌ Erro ao aplicar configuração Nginx${NC}"
    exit 1
}

echo -e "${GREEN}✅ Configuração Nginx aplicada${NC}"
echo ""

# Passo 3: Reiniciar proxy
echo -e "${BLUE}3️⃣  Reiniciando proxy Nginx...${NC}"
az vm run-command invoke \
    -g "$RESOURCE_GROUP" \
    -n "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "cd $PROJECT_DIR && docker compose restart proxy" \
    --output json | jq -r '.value[0].message' || {
    echo -e "${YELLOW}⚠️  Erro ao reiniciar proxy (pode ser que não esteja rodando)${NC}"
    echo "Tente manualmente: docker compose restart proxy"
}

echo -e "${GREEN}✅ Proxy reiniciado${NC}"
echo ""

echo -e "${GREEN}=========================================="
echo "✅ HTTPS Configurado!"
echo "==========================================${NC}"
echo ""
echo "Acesse:"
echo "  - HTTP:  http://$VM_IP (redireciona para HTTPS)"
echo "  - HTTPS: https://$VM_IP"
echo ""
echo -e "${YELLOW}⚠️  NOTA: Certificados auto-assinados gerarão aviso no navegador.${NC}"
echo "   Para produção, use Let's Encrypt ou certificados válidos."
echo ""

