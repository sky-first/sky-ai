#!/bin/bash

# Script: Populate Key Vault Production Secrets
# Purpose: Adicionar secrets ao Key Vault prod para externalSecrets sincronizar
# Usage: ./scripts/populate-kv-prod-secrets.sh <keyvault-name> <env-file>
# Example: ./scripts/populate-kv-prod-secrets.sh akv-sky-prod-xyz .env.prod

set -e

KEYVAULT_NAME="${1:-akv-sky-prod-prod}"
ENV_FILE="${2:-.env}"

if [ ! -f "$ENV_FILE" ]; then
    echo "[ERROR] Arquivo $ENV_FILE não encontrado!"
    echo "Use: $0 <keyvault-name> <env-file>"
    exit 1
fi

echo " Populando Key Vault: $KEYVAULT_NAME"
echo " Lendo variáveis de: $ENV_FILE"
echo ""

# Função para adicionar secret
add_secret() {
    local key=$1
    local value=$2
    
    if [ -z "$value" ]; then
        echo "[WARNING] Pulando $key (valor vazio)"
        return
    fi
    
    echo " Adicionando $key..."
    az keyvault secret set \
        --vault-name "$KEYVAULT_NAME" \
        --name "$key" \
        --value "$value" \
        --output none
    
    echo "[OK] $key criado"
}

# Source .env file
export $(grep -v '^#' "$ENV_FILE" | xargs)

# Secrets a popular (baseado em .env)
add_secret "postgres-password" "$POSTGRES_PASSWORD"
add_secret "redis-password" "$REDIS_PASSWORD"
add_secret "jwt-secret-key" "$JWT_SECRET_KEY"
add_secret "encryption-key" "$ENCRYPTION_KEY"
add_secret "openai-api-key" "$OPENAI_API_KEY"
add_secret "database-url" "$DATABASE_URL"
add_secret "redis-url" "$REDIS_URL"
add_secret "celery-broker-url" "$CELERY_BROKER_URL"

echo ""
echo "[OK] Todos os secrets foram populados no Key Vault!"
echo ""
echo "Próximo passo: Verificar ExternalSecrets sincronizando"
echo "  kubectl get externalsecrets -n prod"
echo "  kubectl get secrets -n prod"
