#!/bin/bash
set -euo pipefail

# Config
ORG="sky-first"
REPO="sky-poc-backend"
BRANCH="staging"
CREDENTIAL_NAME="github-actions-${REPO}-${BRANCH}"
SUBJECT="repo:${ORG}/${REPO}:ref:refs/heads/${BRANCH}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Configuração de Acesso Azure para Backend Staging ===${NC}"
echo "Este script adiciona a credencial federada necessária para o GitHub Actions."
echo ""

# Check deps
if ! command -v az &> /dev/null; then
    echo -e "${RED}Erro: Azure CLI (az) não encontrado.${NC}"
    echo "Instale com: brew install azure-cli (macOS) ou veja docs oficiais."
    exit 1
fi

# Inputs
CLIENT_ID="${1:-}"
TENANT_ID="${2:-}"

if [ -z "$CLIENT_ID" ]; then
    read -p "Digite o Client ID (App Registration ID) usado no GitHub Secrets: " CLIENT_ID
fi

if [ -z "$TENANT_ID" ]; then
    read -p "Digite o Tenant ID do Azure (Directory ID): " TENANT_ID
fi

if [ -z "$CLIENT_ID" ] || [ -z "$TENANT_ID" ]; then
    echo -e "${RED}Erro: Client ID e Tenant ID são obrigatórios.${NC}"
    exit 1
fi

# Login
echo ""
echo -e "${YELLOW}Logando no Azure...${NC}"
az login --tenant "$TENANT_ID" --output none

# Create Credential
echo ""
echo -e "${YELLOW}Criando credencial federada: ${CREDENTIAL_NAME}${NC}"
echo "Subject: $SUBJECT"

PARAMETERS="{\"name\":\"$CREDENTIAL_NAME\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"$SUBJECT\",\"audiences\":[\"api://AzureADTokenExchange\"],\"description\":\"Access for backend staging branch\"}"

if az ad app federated-credential create --id "$CLIENT_ID" --parameters "$PARAMETERS" 2>/dev/null; then
    echo -e "${GREEN}[OK] Sucesso! Credencial criada.${NC}"
else
    # Check execution
    EXISTING=$(az ad app federated-credential list --id "$CLIENT_ID" --query "[?name=='$CREDENTIAL_NAME'].name" -o tsv 2>/dev/null || echo "")
    if [ -n "$EXISTING" ]; then
        echo -e "${GREEN}[OK] Credencial já existe, nada a fazer.${NC}"
    else
        echo -e "${RED}[ERROR] Falha ao criar a credencial. Verifique se você tem permissões de Admin/Owner na App Registration.${NC}"
        # Show verbose error specifically
        az ad app federated-credential create --id "$CLIENT_ID" --parameters "$PARAMETERS"
    fi
fi

echo ""
echo -e "${GREEN}Tudo pronto! Seu workflow de deploy deve funcionar agora.${NC}"
