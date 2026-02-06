#!/bin/bash
# Populate Azure Key Vault Secrets via Azure CLI
# This script is called after Terraform Apply to populate secrets
# Azure CLI is recognized as a trusted service and bypasses the firewall

set -euo pipefail

echo "🔐 Populating Azure Key Vault with secrets..."

# Get variables from Terraform outputs
KEY_VAULT_NAME=$(terraform output -raw key_vault_name)
POSTGRES_PASSWORD=$(terraform output -raw postgres_password)
REDIS_PASSWORD=$(terraform output -raw redis_password)
JWT_SECRET=$(terraform output -raw jwt_secret)
ENCRYPTION_KEY=$(terraform output -raw encryption_key)

# Construct connection strings
DATABASE_URL="postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/ai_saas_db"
REDIS_URL="redis://:${REDIS_PASSWORD}@redis:6379/0"

echo "📦 Target Key Vault: $KEY_VAULT_NAME"
echo ""

# Function to set secret with retry logic
set_secret() {
    local secret_name=$1
    local secret_value=$2
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        ERROR_OUTPUT=$(az keyvault secret set \
            --vault-name "$KEY_VAULT_NAME" \
            --name "$secret_name" \
            --value "$secret_value" \
            --output none 2>&1)
        
        if [ $? -eq 0 ]; then
            echo "  ✅ $secret_name"
            return 0
        else
            retry_count=$((retry_count + 1))
            if [ $retry_count -lt $max_retries ]; then
                echo "  ⚠️  Retry $retry_count/$max_retries for $secret_name..."
                sleep 5
            else
                echo "  ❌ Failed to set $secret_name after $max_retries attempts"
                echo "  📋 Error details: $ERROR_OUTPUT"
            fi
        fi
    done
    
    return 1
}

# Wait for RBAC propagation (Azure CLI needs this too)
echo "⏳ Waiting 30 seconds for RBAC propagation..."
sleep 30
echo ""

echo "📝 Setting secrets in Key Vault..."

# Set all secrets
set_secret "postgres-password" "$POSTGRES_PASSWORD"
set_secret "redis-password" "$REDIS_PASSWORD"
set_secret "database-url" "$DATABASE_URL"
set_secret "redis-url" "$REDIS_URL"
set_secret "jwt-secret-key" "$JWT_SECRET"
set_secret "encryption-key" "$ENCRYPTION_KEY"
set_secret "openai-api-key" "sk-placeholder-replace-me"
set_secret "qdrant-url" "http://qdrant:6333"

echo ""
echo "🎉 All secrets successfully populated in Key Vault!"
echo ""

# Verify secrets were created
echo "🔍 Verifying secrets..."
SECRET_COUNT=$(az keyvault secret list --vault-name "$KEY_VAULT_NAME" --query "length(@)" -o tsv)
echo "  Total secrets in vault: $SECRET_COUNT"

if [ "$SECRET_COUNT" -ge 8 ]; then
    echo "  ✅ All expected secrets are present"
else
    echo "  ⚠️  Expected at least 8 secrets, found $SECRET_COUNT"
fi

echo ""
echo "✨ Key Vault secrets population complete!"
