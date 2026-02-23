#!/bin/bash
# Script para verificar erro 500 no frontend remotamente via Azure CLI
# Uso: ./scripts/azure/check-frontend-500-remote.sh

set -eu

RESOURCE_GROUP="${RESOURCE_GROUP:-POC-SKY}"
VM_NAME="${VM_NAME:-poc-sky}"

echo "=========================================="
echo "🔍 DIAGNÓSTICO REMOTO: Erro HTTP 500"
echo "=========================================="
echo ""
echo "VM: $VM_NAME"
echo "Resource Group: $RESOURCE_GROUP"
echo ""

# Script para executar na VM
DIAGNOSTIC_SCRIPT=$(cat <<'EOF'
#!/bin/bash
set -eu

echo "=========================================="
echo "📊 STATUS DOS CONTAINERS"
echo "=========================================="
echo ""

cd ~/projeto/sky-poc-infra 2>/dev/null || cd ~/projeto/poc-deploy 2>/dev/null || {
    echo "[ERROR] ERRO: Diretório do projeto não encontrado"
    echo "Procurando em:"
    ls -la ~/projeto/ 2>/dev/null || echo "Diretório ~/projeto não existe"
    exit 1
}

echo "[OK] Diretório encontrado: $(pwd)"
echo ""

echo "1.  Status dos containers:"
echo "----------------------------------------"
sudo docker compose ps 2>/dev/null || docker compose ps 2>/dev/null || {
    echo "[WARNING] docker compose não encontrado, tentando docker ps..."
    sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | head -20
}

echo ""
echo "=========================================="
echo "📋 LOGS DO FRONTEND (últimas 100 linhas)"
echo "=========================================="
echo ""

FRONTEND_CONTAINER=$(sudo docker ps --format "{{.Names}}" | grep -E "frontend" | head -1)

if [ -n "$FRONTEND_CONTAINER" ]; then
    echo "[OK] Container frontend encontrado: $FRONTEND_CONTAINER"
    echo ""
    echo "Logs recentes:"
    echo "----------------------------------------"
    sudo docker logs --tail=100 "$FRONTEND_CONTAINER" 2>&1 | tail -100
else
    echo "[ERROR] Container frontend não encontrado"
    echo "Containers disponíveis:"
    sudo docker ps --format "{{.Names}}" | head -10
fi

echo ""
echo "=========================================="
echo "📋 LOGS DO NGINX/PROXY (últimas 50 linhas)"
echo "=========================================="
echo ""

PROXY_CONTAINER=$(sudo docker ps --format "{{.Names}}" | grep -E "proxy|nginx" | head -1)

if [ -n "$PROXY_CONTAINER" ]; then
    echo "[OK] Container proxy encontrado: $PROXY_CONTAINER"
    echo ""
    echo "Logs recentes:"
    echo "----------------------------------------"
    sudo docker logs --tail=50 "$PROXY_CONTAINER" 2>&1 | tail -50
else
    echo "[WARNING] Container proxy não encontrado"
fi

echo ""
echo "=========================================="
echo "📋 LOGS DO BACKEND (últimas 30 linhas)"
echo "=========================================="
echo ""

BACKEND_CONTAINER=$(sudo docker ps --format "{{.Names}}" | grep -E "backend" | head -1)

if [ -n "$BACKEND_CONTAINER" ]; then
    echo "[OK] Container backend encontrado: $BACKEND_CONTAINER"
    echo ""
    echo "Logs recentes:"
    echo "----------------------------------------"
    sudo docker logs --tail=30 "$BACKEND_CONTAINER" 2>&1 | tail -30
else
    echo "[WARNING] Container backend não encontrado"
fi

echo ""
echo "=========================================="
echo "🔍 VERIFICAÇÃO DE VARIÁVEIS DE AMBIENTE"
echo "=========================================="
echo ""

if [ -f .env ]; then
    echo "[OK] Arquivo .env encontrado"
    echo ""
    echo "NEXT_PUBLIC_API_URL:"
    grep "NEXT_PUBLIC_API_URL" .env | head -1 || echo "[ERROR] NEXT_PUBLIC_API_URL não encontrado"
    echo ""
    echo "DATABASE_URL (primeiros caracteres):"
    grep "DATABASE_URL" .env | head -1 | sed 's/\(.*:\)\(.*\)\(@.*\)/\1***\3/' || echo "DATABASE_URL não encontrado"
else
    echo "[ERROR] Arquivo .env não encontrado"
    echo "Arquivos no diretório:"
    ls -la | head -10
fi

echo ""
echo "=========================================="
echo "🌐 TESTE DE CONECTIVIDADE INTERNA"
echo "=========================================="
echo ""

echo "Testando backend via proxy (localhost)..."
if curl -s --max-time 5 http://localhost/health > /dev/null 2>&1; then
    echo "[OK] Backend responde via proxy (localhost/health)"
    curl -s --max-time 5 http://localhost/health | head -3
else
    echo "[ERROR] Backend não responde via proxy (localhost/health)"
fi

echo ""
echo "Testando frontend via proxy (localhost)..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost 2>/dev/null || echo "000")
if [ "$HTTP_CODE" != "000" ]; then
    echo "[OK] Frontend responde via proxy (HTTP $HTTP_CODE)"
else
    echo "[ERROR] Frontend não responde via proxy (localhost)"
fi

echo ""
echo "=========================================="
echo "📊 RESUMO DO DIAGNÓSTICO"
echo "=========================================="
echo ""

# Verificar se frontend está rodando
if sudo docker ps --format "{{.Names}}" | grep -qE "frontend"; then
    FRONTEND_STATUS=$(sudo docker ps --format "{{.Status}}" --filter "name=frontend" | head -1)
    echo "[OK] Frontend container: $FRONTEND_STATUS"
else
    echo "[ERROR] Frontend container NÃO está rodando"
fi

# Verificar se backend está rodando
if sudo docker ps --format "{{.Names}}" | grep -qE "backend"; then
    BACKEND_STATUS=$(sudo docker ps --format "{{.Status}}" --filter "name=backend" | head -1)
    echo "[OK] Backend container: $BACKEND_STATUS"
else
    echo "[ERROR] Backend container NÃO está rodando"
fi

# Verificar se proxy está rodando
if sudo docker ps --format "{{.Names}}" | grep -qE "proxy|nginx"; then
    PROXY_STATUS=$(sudo docker ps --format "{{.Status}}" --filter "name=proxy" --filter "name=nginx" | head -1)
    echo "[OK] Proxy/Nginx container: $PROXY_STATUS"
else
    echo "[ERROR] Proxy/Nginx container NÃO está rodando"
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
    echo "[ERROR] ERRO: Não foi possível executar diagnóstico via Azure CLI"
    echo ""
    echo "Possíveis causas:"
    echo "  - Azure CLI não está autenticado (execute: az login)"
    echo "  - VM não está acessível"
    echo "  - Permissões insuficientes"
    echo ""
    echo "Execute manualmente na VM:"
    echo "  ssh azureuser@20.86.142.1"
    echo "  cd ~/projeto/sky-poc-infra"
    echo "  sudo docker compose logs frontend --tail=100"
    exit 1
}

echo ""
echo "=========================================="
echo "[OK] Diagnóstico concluído"
echo "=========================================="

