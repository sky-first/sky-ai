#!/bin/bash
# scripts/executar-deploy.sh
# Script helper para executar deploy com configurações corretas

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configurar variáveis
export VM_IP=172.191.77.30
export BRANCH=staging
export SSH_KEY=~/.ssh/id_ed25519

echo "🚀 Configurações:"
echo "  VM_IP: $VM_IP"
echo "  BRANCH: $BRANCH"
echo "  SSH_KEY: $SSH_KEY"
echo ""

# Verificar se .env existe
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "❌ .env não encontrado!"
    echo "Execute primeiro: ./scripts/fix-env-secrets.sh"
    exit 1
fi

echo "✅ .env encontrado"

# Verificar se GH_PAT está configurado (necessário para repositórios privados)
if [ -z "${GH_PAT:-}" ]; then
    echo ""
    echo "⚠️  GH_PAT não configurado!"
    echo "Repositórios são privados, configure o token:"
    echo "  export GH_PAT=ghp_seu_token_aqui"
    echo ""
    echo "Para criar um token:"
    echo "  1. GitHub > Settings > Developer settings > Personal access tokens > Tokens (classic)"
    echo "  2. Generate new token (classic)"
    echo "  3. Selecione escopo: repo (acesso completo aos repositórios)"
    echo ""
    read -p "Deseja continuar sem GH_PAT? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ GH_PAT configurado"
fi

echo ""
echo "🚀 Iniciando deploy..."
echo ""

cd "$PROJECT_DIR"
./scripts/deploy-local-to-vm.sh

