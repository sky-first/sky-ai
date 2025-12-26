#!/bin/bash
# scripts/validate-secrets.sh
# Valida existência e complexidade de secrets no Azure Key Vault

set -e

KV_NAME="${KEYVAULT_NAME:-}"
REQUIRED_SECRETS=(
  "POSTGRES_PASSWORD"
  "REDIS_PASSWORD"
  "JWT_SECRET_KEY"
  "ENCRYPTION_KEY"
)

if [ -z "$KV_NAME" ]; then
  echo "❌ KEYVAULT_NAME não definido"
  echo "   Exporte: export KEYVAULT_NAME=seu-keyvault"
  exit 1
fi

echo "🔐 Validando secrets no Key Vault: $KV_NAME"
echo ""

FAILED=0
WARNINGS=0

for secret in "${REQUIRED_SECRETS[@]}"; do
  echo -n "Verificando $secret... "
  
  # Verificar existência
  VALUE=$(az keyvault secret show \
    --vault-name "$KV_NAME" \
    --name "$secret" \
    --query value -o tsv 2>/dev/null || echo "")
  
  if [ -z "$VALUE" ]; then
    echo "❌ NÃO ENCONTRADO"
    FAILED=$((FAILED + 1))
    continue
  fi
  
  # Verificar complexidade
  LENGTH=${#VALUE}
  if [ $LENGTH -lt 32 ]; then
    echo "⚠️  Muito curto (${LENGTH} caracteres, mínimo 32)"
    WARNINGS=$((WARNINGS + 1))
  else
    echo "✅ OK (${LENGTH} caracteres)"
  fi
done

echo ""
if [ $FAILED -gt 0 ]; then
  echo "❌ $FAILED secret(s) não encontrado(s)"
  exit 1
fi

if [ $WARNINGS -gt 0 ]; then
  echo "⚠️  $WARNINGS aviso(s) de complexidade"
  echo "   Considere rotacionar secrets com maior complexidade"
fi

echo "✅ Todos os secrets estão presentes"

