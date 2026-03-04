#!/bin/bash
set -e

# Usage: ./sync-secrets.sh <env-file> <namespace>
# Example: ./sync-secrets.sh ../../.env backend

ENV_FILE=${1:-"../../.env"}
NAMESPACE=${2:-"backend"}

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi

echo "Loading secrets from $ENV_FILE to kubectl context..."

# Extract values (ignoring comments and empty lines)
JWT=$(grep "^JWT_SECRET_KEY=" "$ENV_FILE" | cut -d'=' -f2-)
ENC=$(grep "^ENCRYPTION_KEY=" "$ENV_FILE" | cut -d'=' -f2-)
OPENAI=$(grep "^OPENAI_API_KEY=" "$ENV_FILE" | cut -d'=' -f2-)
SENTRY=$(grep "^SENTRY_DSN=" "$ENV_FILE" | cut -d'=' -f2-)

if [ -z "$JWT" ]; then echo "Warning: JWT_SECRET_KEY not found"; fi
if [ -z "$OPENAI" ]; then echo "Warning: OPENAI_API_KEY not found"; fi

# Encode existing database/redis URLs from Terraform outputs would be better,
# but here we are syncing APP level secrets.

# Create Namespace if not exists
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# Create Secret
kubectl create secret generic app-secrets \
    --namespace "$NAMESPACE" \
    --from-literal=jwt-secret-key="$JWT" \
    --from-literal=encryption-key="$ENC" \
    --from-literal=openai-api-key="$OPENAI" \
    --from-literal=sentry-dsn="$SENTRY" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "✅ Secrets synced to namespace '$NAMESPACE'!"
