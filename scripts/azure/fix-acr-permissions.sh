#!/bin/bash
set -euo pipefail

# Config
ACR_NAME="skyacrstagingj3minh"
RESOURCE_GROUP="sky-aks-staging-rg"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Corrigindo Permissões de ACR para GitHub Actions (OIDC) ===${NC}"
echo "Este script concede a permissão 'AcrPush' para o Service Principal usado no GitHub."
echo ""

# Check deps
if ! command -v az &> /dev/null; then
    echo -e "${RED}Erro: Azure CLI (az) não encontrado.${NC}"
    exit 1
fi

# Inputs
CLIENT_ID="${1:-}"

if [ -z "$CLIENT_ID" ]; then
    echo -e "${YELLOW}Dica: O Client ID é o 'Application ID' da App Registration no Azure AD,${NC}"
    echo -e "${YELLOW}o mesmo valor que você colocou no secret AZURE_CLIENT_ID do GitHub.${NC}"
    read -p "Digite o Client ID do GitHub Actions: " CLIENT_ID
fi

if [ -z "$CLIENT_ID" ]; then
    echo -e "${RED}Erro: Client ID é obrigatório.${NC}"
    exit 1
fi

# Obter o ID do ACR
echo "Buscando ID do registro: $ACR_NAME..."
ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv 2>/dev/null || echo "")

if [ -z "$ACR_ID" ]; then
    echo -e "${RED}Erro: ACR '$ACR_NAME' não encontrado no Resource Group '$RESOURCE_GROUP'.${NC}"
    echo "Verifique se o nome do ACR e do Resource Group estão corretos."
    exit 1
fi

echo -e "${GREEN}✅ Registro encontrado: $ACR_ID${NC}"

# Obter o Service Principal Object ID
echo "Buscando ID da App Registration..."
SP_ID=$(az ad sp show --id "$CLIENT_ID" --query id -o tsv 2>/dev/null || echo "")

if [ -z "$SP_ID" ]; then
    echo -e "${RED}Erro: Service Principal com Client ID '$CLIENT_ID' não encontrado.${NC}"
    echo "Verifique se o Client ID está correto e se você tem acesso ao tenant.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Service Principal ID: $SP_ID${NC}"

# Atribuir role AcrPush
echo "Concedendo permissão AcrPush (leitura/escrita de imagens)..."
if az role assignment create \
    --assignee "$SP_ID" \
    --role "AcrPush" \
    --scope "$ACR_ID" 2>/dev/null; then
    echo -e "${GREEN}✅ Sucesso! Permissão AcrPush concedida.${NC}"
else
    # Verificando se já existe
    EXISTING=$(az role assignment list --assignee "$SP_ID" --scope "$ACR_ID" --role "AcrPush" --query "[].id" -o tsv 2>/dev/null || echo "")
    if [ -n "$EXISTING" ]; then
        echo -e "${GREEN}✅ Permissão já existe.${NC}"
    else
        echo -e "${RED}❌ Falha ao atribuir permissão. Verifique se você é 'Owner' ou 'User Access Administrator'.${NC}"
        # Repete com erro visível
        az role assignment create --assignee "$SP_ID" --role "AcrPush" --scope "$ACR_ID"
    fi
fi

echo ""
echo -e "${GREEN}Pronto! Tente rodar o workflow no GitHub novamente.${NC}"
