#!/bin/bash
# Populate Azure Key Vault Secrets via Azure CLI
# This script is called after Terraform Apply to populate secrets
# Azure CLI is recognized as a trusted service and bypasses the firewall

set -euo pipefail

echo "🔐 Populating Azure Key Vault with secrets..."

# JIT Firewall Management Variables
CURRENT_IP=""
FIREWALL_ADDED=false

# Function to cleanup JIT firewall rule
cleanup_firewall() {
    if [ "$FIREWALL_ADDED" = "true" ] && [ -n "$CURRENT_IP" ]; then
        echo "🧹 Cleaning up JIT firewall rule for IP: $CURRENT_IP..."
        az keyvault network-rule remove \
            --name "$KEY_VAULT_NAME" \
            --ip-address "$CURRENT_IP/32" \
            --only-show-errors >/dev/null 2>&1 || true
        echo "✅ Cleanup complete."
    fi
}

# Register cleanup on exit
trap cleanup_firewall EXIT

# Get variables from Terraform outputs with fallback/validation
echo "🔍 Fetching secrets from Terraform outputs..."
KEY_VAULT_NAME=${KEY_VAULT_NAME:-$(terraform output -raw key_vault_name 2>/dev/null || echo "")}
POSTGRES_PASSWORD=$(terraform output -raw postgres_password 2>/dev/null || echo "")
REDIS_PASSWORD=$(terraform output -raw redis_password 2>/dev/null || echo "")
JWT_SECRET=$(terraform output -raw jwt_secret 2>/dev/null || echo "")
ENCRYPTION_KEY=$(terraform output -raw encryption_key 2>/dev/null || echo "")

if [ -z "$KEY_VAULT_NAME" ]; then
    echo "❌ ERROR: Could not get key_vault_name from Terraform outputs"
    terraform output
    exit 1
fi

# Atomic IP Detection and Whitelisting
echo "📍 Detecting current outbound IP..."
CURRENT_IP=$(curl -s https://api.ipify.org || curl -s https://ifconfig.me)
if [ -z "$CURRENT_IP" ]; then
    echo "⚠️ Warning: Could not detect outbound IP. Proceeding with existing whitelist..."
else
    echo "✅ Current Outbound IP: $CURRENT_IP"
    echo "🔓 Whitelisting IP in Key Vault $KEY_VAULT_NAME..."
    if az keyvault network-rule add \
        --name "$KEY_VAULT_NAME" \
        --ip-address "$CURRENT_IP/32" \
        --only-show-errors >/dev/null 2>&1; then
        echo "✅ IP $CURRENT_IP added to whitelist."
        FIREWALL_ADDED="true"
        echo "⏳ Waiting 15s for rule propagation..."
        sleep 15
    else
        echo "ℹ️  Could not add IP (maybe already whitelisted or internal access only)."
    fi
fi

echo "📦 Target Key Vault: $KEY_VAULT_NAME"
echo ""

# Function to set secret with retry logic
set_secret() {
    local secret_name=$1
    local secret_value=$2
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        echo "  Attempting to set $secret_name (try $((retry_count + 1))/$max_retries)..."
        
        # We use set +e / set -e or a helper to avoid crashing the script on failure
        # so we can actually see the error message
        set +e
        ERROR_OUTPUT=$(az keyvault secret set \
            --vault-name "$KEY_VAULT_NAME" \
            --name "$secret_name" \
            --value "$secret_value" \
            --output none 2>&1)
        EXIT_CODE=$?
        set -e
        
        if [ $EXIT_CODE -eq 0 ]; then
            echo "  ✅ $secret_name set successfully"
            return 0
        else
            echo "  ⚠️  Failed to set $secret_name: $ERROR_OUTPUT"
            retry_count=$((retry_count + 1))
            if [ $retry_count -lt $max_retries ]; then
                echo "  ⏳ Retrying in 10s..."
                sleep 10
            else
                echo "  ❌ Final failure for $secret_name after $max_retries attempts"
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
DATABASE_URL="postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/ai_saas_db"
REDIS_URL="redis://:${REDIS_PASSWORD}@redis:6379/0"

set_secret "postgres-password" "$POSTGRES_PASSWORD"
set_secret "redis-password" "$REDIS_PASSWORD"
set_secret "database-url" "$DATABASE_URL"
set_secret "redis-url" "$REDIS_URL"
set_secret "jwt-secret-key" "$JWT_SECRET"
set_secret "encryption-key" "$ENCRYPTION_KEY"
set_secret "openai-api-key" "${OPENAI_API_KEY:-sk-placeholder-replace-me}"
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
