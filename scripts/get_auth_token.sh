#!/bin/bash
set -e

echo "Obtendo token de autenticação..."
RESPONSE=$(curl -s -X POST https://workspace-stg.skyfirstlabs.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@skyfirstlabs.com", "password": "SkyFirst@2026!"}')

# Tenta extrair token (ajuste conforme resposta real da API)
# Assumindo formato: {"access_token": "..."} ou similar
TOKEN=$(echo $RESPONSE | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
  # Fallback para estrutura {"token": "..."} ou apenas verificar se houve erro
  TOKEN=$(echo $RESPONSE | grep -o '"token":"[^"]*' | cut -d'"' -f4)
fi

if [ -z "$TOKEN" ]; then
  echo "Erro ao obter token:"
  echo "$RESPONSE"
  exit 1
fi

echo "$TOKEN"
