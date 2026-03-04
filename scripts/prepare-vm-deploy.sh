#!/bin/bash
# scripts/prepare-vm-deploy.sh
# Script para preparar deploy na VM (validações Terraform)

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

echo -e "${BLUE} Preparando deploy na VM...${NC}"
echo ""

# 1. Verificar Terraform
echo -e "${BLUE}1. Verificando Terraform...${NC}"
if ! command -v terraform &> /dev/null; then
  echo -e "${RED}[ERROR] Terraform não está instalado${NC}"
  exit 1
fi

echo -e "${GREEN}[OK] Terraform instalado: $(terraform version | head -1)${NC}"

# 2. Verificar Azure CLI
echo ""
echo -e "${BLUE}2. Verificando Azure CLI...${NC}"
if ! command -v az &> /dev/null; then
  echo -e "${RED}[ERROR] Azure CLI não está instalado${NC}"
  exit 1
fi

# Verificar login
if ! az account show &> /dev/null; then
  echo -e "${RED}[ERROR] Não está logado no Azure${NC}"
  echo -e "${YELLOW}   Execute: az login${NC}"
  exit 1
fi

echo -e "${GREEN}[OK] Azure CLI instalado e autenticado${NC}"

# 3. Verificar arquivos Terraform
echo ""
echo -e "${BLUE}3. Verificando arquivos Terraform...${NC}"
cd "$TF_DIR"

if [ ! -f "terraform.tfvars.prod" ]; then
  echo -e "${RED}[ERROR] terraform.tfvars.prod não encontrado${NC}"
  exit 1
fi

echo -e "${GREEN}[OK] terraform.tfvars.prod encontrado${NC}"

# 4. Terraform Init
echo ""
echo -e "${BLUE}4. Inicializando Terraform...${NC}"
if terraform init &> /dev/null; then
  echo -e "${GREEN}[OK] Terraform inicializado${NC}"
else
  echo -e "${YELLOW}[WARNING] Executando terraform init (pode demorar)...${NC}"
  terraform init
fi

# 5. Terraform Validate
echo ""
echo -e "${BLUE}5. Validando configuração Terraform...${NC}"
if terraform validate; then
  echo -e "${GREEN}[OK] Configuração Terraform válida${NC}"
else
  echo -e "${RED}[ERROR] Erro na validação Terraform${NC}"
  exit 1
fi

# 6. Verificar workspace
echo ""
echo -e "${BLUE}6. Verificando workspace...${NC}"
CURRENT_WS=$(terraform workspace show 2>/dev/null || echo "default")

if [ "$CURRENT_WS" != "prod" ]; then
  echo -e "${YELLOW}[WARNING] Workspace atual: $CURRENT_WS${NC}"
  echo -e "${YELLOW}   Criando/selecionando workspace 'prod'...${NC}"
  terraform workspace select prod || terraform workspace new prod
else
  echo -e "${GREEN}[OK] Workspace 'prod' selecionado${NC}"
fi

# 7. Terraform Plan (dry-run)
echo ""
echo -e "${BLUE}7. Executando terraform plan (dry-run)...${NC}"
echo -e "${YELLOW}   Isso pode demorar alguns minutos...${NC}"
echo ""

if terraform plan -var-file=terraform.tfvars.prod -out=tfplan; then
  echo ""
  echo -e "${GREEN}[OK] Terraform plan executado com sucesso${NC}"
  echo -e "${YELLOW}   Plan salvo em: tfplan${NC}"
  echo ""
  echo -e "${BLUE}Para aplicar:${NC}"
  echo -e "  ${YELLOW}terraform apply tfplan${NC}"
else
  echo -e "${RED}[ERROR] Erro no terraform plan${NC}"
  exit 1
fi

# 8. Verificar chaves SSH
echo ""
echo -e "${BLUE}8. Verificando chaves SSH...${NC}"
SSH_KEY_PATH="$PROJECT_DIR/keys/azure/id_rsa.pub"
if [ -f "$SSH_KEY_PATH" ]; then
  echo -e "${GREEN}[OK] Chave pública SSH encontrada${NC}"
else
  echo -e "${YELLOW}[WARNING] Chave pública SSH não encontrada em: $SSH_KEY_PATH${NC}"
fi

# 9. Resumo
echo ""
echo -e "${GREEN}[OK] Preparação para deploy na VM concluída!${NC}"
echo ""
echo -e "${BLUE}Próximos passos:${NC}"
echo -e "  1. Revisar o plan: ${YELLOW}terraform show tfplan${NC}"
echo -e "  2. Aplicar: ${YELLOW}terraform apply tfplan${NC}"
echo -e "  3. Aguardar criação da VM e deploy automático"
echo -e "  4. Obter IP: ${YELLOW}terraform output vm_public_ip${NC}"
echo ""

