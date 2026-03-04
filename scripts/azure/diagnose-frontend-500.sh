#!/bin/bash
# Script para diagnosticar erro HTTP 500 no frontend
# Uso: ./scripts/azure/diagnose-frontend-500.sh <VM_IP> <RESOURCE_GROUP> <VM_NAME>

set -eu

VM_IP="${1:-20.86.142.1}"
RESOURCE_GROUP="${2:-POC-SKY}"
VM_NAME="${3:-poc-sky}"

echo "=========================================="
echo "🔍 DIAGNÓSTICO: Erro HTTP 500 no Frontend"
echo "=========================================="
echo ""
echo "VM: $VM_NAME"
echo "IP: $VM_IP"
echo "Resource Group: $RESOURCE_GROUP"
echo ""

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Comando para executar na VM
DIAGNOSTIC_SCRIPT=$(cat <<'EOF'
#!/bin/bash
set -eu

echo "=========================================="
echo "📊 STATUS DOS CONTAINERS"
echo "=========================================="
echo ""

cd ~/projeto/sky-poc-infra 2>/dev/null || cd ~/projeto/poc-deploy 2>/dev/null || {
    echo "❌ ERRO: Diretório do projeto não encontrado"
    exit 1
}

echo "1️⃣  Verificando containers Docker..."
echo ""
sudo docker compose ps 2>/dev/null || docker compose ps 2>/dev/null || {
    echo "❌ ERRO: docker compose não encontrado ou sem permissão"
    exit 1
}

echo ""
echo "=========================================="
echo "📋 LOGS DO FRONTEND (últimas 50 linhas)"
echo "=========================================="
echo ""
sudo docker compose logs --tail=50 frontend 2>/dev/null || docker compose logs --tail=50 frontend 2>/dev/null || {
    echo "⚠️  Não foi possível obter logs do frontend"
}

echo ""
echo "=========================================="
echo "📋 LOGS DO NGINX/PROXY (últimas 50 linhas)"
echo "=========================================="
echo ""
sudo docker compose logs --tail=50 proxy 2>/dev/null || docker compose logs --tail=50 proxy 2>/dev/null || {
    echo "⚠️  Não foi possível obter logs do proxy"
}

echo ""
echo "=========================================="
echo "📋 LOGS DO BACKEND (últimas 30 linhas)"
echo "=========================================="
echo ""
sudo docker compose logs --tail=30 backend 2>/dev/null || docker compose logs --tail=30 backend 2>/dev/null || {
    echo "⚠️  Não foi possível obter logs do backend"
}

echo ""
echo "=========================================="
echo "🔍 VERIFICAÇÃO DE VARIÁVEIS DE AMBIENTE"
echo "=========================================="
echo ""

if [ -f .env ]; then
    echo "✅ Arquivo .env encontrado"
    echo ""
    echo "Verificando NEXT_PUBLIC_API_URL:"
    if grep -q "NEXT_PUBLIC_API_URL" .env; then
        grep "NEXT_PUBLIC_API_URL" .env | head -1
    else
        echo "❌ NEXT_PUBLIC_API_URL não encontrado no .env"
    fi
    echo ""
else
    echo "❌ Arquivo .env não encontrado"
fi

echo ""
echo "=========================================="
echo "🌐 TESTE DE CONECTIVIDADE INTERNA"
echo "=========================================="
echo ""

echo "Testando backend via proxy..."
if curl -s --max-time 5 http://localhost/health > /dev/null 2>&1; then
    echo "✅ Backend responde via proxy (localhost/health)"
    curl -s --max-time 5 http://localhost/health | head -3
else
    echo "❌ Backend não responde via proxy (localhost/health)"
fi

echo ""
echo "Testando frontend via proxy..."
if curl -s --max-time 5 http://localhost > /dev/null 2>&1; then
    echo "✅ Frontend responde via proxy (localhost)"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost)
    echo "   HTTP Status: $HTTP_CODE"
else
    echo "❌ Frontend não responde via proxy (localhost)"
fi

echo ""
echo "=========================================="
echo "📊 RESUMO DO DIAGNÓSTICO"
echo "=========================================="
echo ""

# Verificar se frontend está rodando
if sudo docker compose ps frontend 2>/dev/null | grep -q "Up\|running"; then
    echo "✅ Frontend container está rodando"
else
    echo "❌ Frontend container NÃO está rodando"
fi

# Verificar se backend está rodando
if sudo docker compose ps backend 2>/dev/null | grep -q "Up\|running"; then
    echo "✅ Backend container está rodando"
else
    echo "❌ Backend container NÃO está rodando"
fi

# Verificar se proxy está rodando
if sudo docker compose ps proxy 2>/dev/null | grep -q "Up\|running"; then
    echo "✅ Proxy/Nginx container está rodando"
else
    echo "❌ Proxy/Nginx container NÃO está rodando"
fi

echo ""
echo "=========================================="
EOF
)

echo "Executando diagnóstico na VM..."
echo ""

# Executar via Azure CLI Run Command
az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "$DIAGNOSTIC_SCRIPT" \
    --output table 2>&1 || {
    echo "❌ ERRO: Não foi possível executar diagnóstico via Azure CLI"
    echo ""
    echo "Execute manualmente na VM:"
    echo "  ssh azureuser@$VM_IP"
    echo "  cd ~/projeto/sky-poc-infra"
    echo "  sudo docker compose ps"
    echo "  sudo docker compose logs frontend --tail=50"
    exit 1
}

echo ""
echo "=========================================="
echo "✅ Diagnóstico concluído"
echo "=========================================="

