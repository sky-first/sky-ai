#!/bin/bash
# Script para garantir que .env existe na VM
# Pode ser executado via Azure CLI run-command ou diretamente na VM

set -euo pipefail

BASE=~/projeto
if [ -d "$BASE/sky-poc-infra" ]; then
    INFRA_DIR="$BASE/sky-poc-infra"
elif [ -d "$BASE/poc-deploy" ]; then
    INFRA_DIR="$BASE/poc-deploy"
else
    echo "❌ ERRO: Diretório de infraestrutura não encontrado"
    echo "   Procurou em: $BASE/sky-poc-infra e $BASE/poc-deploy"
    exit 1
fi

cd "$INFRA_DIR"
echo "📁 Diretório: $INFRA_DIR"
echo ""

# Verificar se .env existe
if [ -f .env ]; then
    echo "✅ Arquivo .env existe"
    ls -lh .env
    echo ""
    echo "📋 Primeiras linhas do .env (valores sensíveis ocultos):"
    head -20 .env | sed 's/=.*/=***/' || true
    echo ""
    exit 0
fi

# .env não existe, criar a partir de env.example
echo "⚠️  Arquivo .env NÃO existe"
echo ""

if [ ! -f env.example ]; then
    echo "❌ ERRO: env.example também não encontrado!"
    echo "   Caminho esperado: $INFRA_DIR/env.example"
    ls -la "$INFRA_DIR" | head -20
    exit 1
fi

echo "📝 Criando .env a partir de env.example..."
cp env.example .env
chmod 600 .env

echo "✅ .env criado com sucesso!"
echo ""
echo "📋 Verificando conteúdo:"
ls -lh .env
echo ""
echo "⚠️  IMPORTANTE: Configure as variáveis sensíveis no .env:"
echo "   - POSTGRES_PASSWORD"
echo "   - REDIS_PASSWORD"
echo "   - JWT_SECRET_KEY"
echo "   - ENCRYPTION_KEY"
echo "   - OPENAI_API_KEY (se necessário)"
echo ""
echo "   Você pode editar com: nano .env"
echo ""

