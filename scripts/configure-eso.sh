#!/bin/bash
set -e

# Usage: ./configure-eso.sh [env-name]
# Defaults to "staging" if not provided.

ENV_NAME=${1:-"staging"}
INFRA_DIR="./infra/aks"
GITOPS_DIR="./gitops"

echo "Configuring External Secrets Operator for environment: $ENV_NAME"

# 1. Get Terraform Outputs
cd "$INFRA_DIR"
echo "Fetching Terraform outputs..."
ESO_CLIENT_ID=$(terraform output -raw eso_client_id 2>/dev/null || echo "")
KV_NAME=$(terraform output -raw key_vault_name 2>/dev/null || echo "")
TENANT_ID=$(az account show --query tenantId -o tsv)

if [ -z "$ESO_CLIENT_ID" ] || [ -z "$KV_NAME" ]; then
    echo "Error: Could not fetch Terraform outputs. Did you run 'terraform apply'?"
    echo "ESO_CLIENT_ID: $ESO_CLIENT_ID"
    echo "KV_NAME: $KV_NAME"
    exit 1
fi

cd - > /dev/null

# 2. Update External Secrets App Manifest (Inject Client ID)
ES_MANIFEST="$GITOPS_DIR/bootstrap/external-secrets.yaml"
echo "Updating $ES_MANIFEST..."

# Use sed to replace placeholders. 
# We use a temp file logic for cross-OS compatibility.
sed "s|\${ESO_CLIENT_ID}|$ESO_CLIENT_ID|g" "$ES_MANIFEST" > "${ES_MANIFEST}.tmp" && mv "${ES_MANIFEST}.tmp" "$ES_MANIFEST"
sed "s|\${TENANT_ID}|$TENANT_ID|g" "$ES_MANIFEST" > "${ES_MANIFEST}.tmp" && mv "${ES_MANIFEST}.tmp" "$ES_MANIFEST"

# 3. Update ClusterSecretStore (Inject Vault URL)
CSS_MANIFEST="$GITOPS_DIR/manifests/security/cluster-secret-store.yaml"
VAULT_URL="https://${KV_NAME}.vault.azure.net"

echo "Updating $CSS_MANIFEST with Vault URL: $VAULT_URL"
# Regex matches "vaultUrl: .*" and replaces it
sed "s|vaultUrl: \".*\"|vaultUrl: \"$VAULT_URL\"|g" "$CSS_MANIFEST" > "${CSS_MANIFEST}.tmp" && mv "${CSS_MANIFEST}.tmp" "$CSS_MANIFEST"

echo "✅ Configuration updated!"
echo "   - ESO Client ID: $ESO_CLIENT_ID"
echo "   - Key Vault URL: $VAULT_URL"
echo ""
echo "Next Steps:"
echo "1. Commit and push these changes to Git."
echo "2. ArgoCD will sync and install External Secrets."
