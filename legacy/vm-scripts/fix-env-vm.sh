#!/bin/bash
# Script para verificar e criar .env na VM via Azure CLI

set -euo pipefail

RESOURCE_GROUP="POC-SKY"
VM_NAME="poc-sky"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "🔧 Verificando/Criando .env na VM"
echo "==========================================${NC}"
echo ""

# Executar script na VM
OUTPUT=$(az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts '
      set -euo pipefail
      
      # Usar caminho absoluto e fallback para compatibilidade
      BASE=\"/home/azureuser/projeto\"
      if [ ! -d \"$BASE\" ]; then
        BASE=\"${HOME:-/home/azureuser}/projeto\"
      fi
      
      if [ -d \"$BASE/sky-poc-infra\" ]; then
        INFRA_DIR=\"$BASE/sky-poc-infra\"
      elif [ -d \"$BASE/poc-deploy\" ]; then
        INFRA_DIR=\"$BASE/poc-deploy\"
      else
        echo \"❌ ERRO: Diretório não encontrado em $BASE (nem sky-poc-infra nem poc-deploy)\"
        exit 1
      fi
      
      cd "$INFRA_DIR"
      echo "📁 Diretório: $INFRA_DIR"
      echo ""
      
      if [ -f .env ]; then
        echo "✅ Arquivo .env existe"
        ls -lh .env
        echo ""
        echo "📋 Verificando variáveis importantes:"
        for var in POSTGRES_PASSWORD REDIS_PASSWORD JWT_SECRET_KEY ENCRYPTION_KEY NEXT_PUBLIC_API_URL; do
          if grep -q "^${var}=" .env; then
            echo "  ✅ $var está definida"
          else
            echo "  ⚠️  $var NÃO está definida"
          fi
        done
      else
        echo "⚠️  Arquivo .env NÃO existe"
        echo ""
        
        if [ -f env.example ]; then
          echo "📝 Criando .env a partir de env.example..."
          cp env.example .env
          chmod 600 .env
          echo "✅ .env criado com sucesso!"
          ls -lh .env
        else
          echo "❌ ERRO: env.example também não encontrado!"
          ls -la | head -20
          exit 1
        fi
      fi
    ' \
    --query "value[0].message" -o tsv 2>/dev/null || echo "")

echo "$OUTPUT"

# Verificar se foi bem-sucedido
if echo "$OUTPUT" | grep -q "✅ Arquivo .env existe\|✅ .env criado"; then
    echo ""
    echo -e "${GREEN}✅ Sucesso!${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}❌ Falha ao verificar/criar .env${NC}"
    exit 1
fi

