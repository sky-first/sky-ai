#!/bin/bash
# Script simplificado para aplicar healthcheck via Azure CLI
set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

echo "Aplicando healthcheck na VM..."

# Script simplificado
APPLY_SCRIPT='set -eu
cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || exit 1

# Verificar se healthcheck já existe
if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo "✅ Healthcheck já existe"
else
    echo "Aplicando healthcheck..."
    cp docker-compose.yml docker-compose.yml.backup
    
    # Adicionar healthcheck após networks (linha que contém "- ai_saas_network")
    awk "/- ai_saas_network/ { print; print \"    # Healthcheck para garantir que Next.js está pronto\"; print \"    healthcheck:\"; print \"      test: [\\\"CMD\\\", \\\"wget\\\", \\\"--quiet\\\", \\\"--tries=1\\\", \\\"--spider\\\", \\\"http://localhost:3000/ || exit 1\\\"]\"; print \"      interval: 30s\"; print \"      timeout: 10s\"; print \"      retries: 5\"; print \"      start_period: 90s\"; next }1" docker-compose.yml > docker-compose.yml.tmp
    mv docker-compose.yml.tmp docker-compose.yml
    
    if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
        echo "✅ Healthcheck aplicado"
    else
        echo "❌ Erro ao aplicar healthcheck"
        exit 1
    fi
fi

# Verificar depends_on
if ! grep -A 5 "proxy:" docker-compose.yml | grep -A 3 "depends_on:" | grep -q "service_healthy"; then
    echo "Ajustando depends_on..."
    sed -i "s/frontend:.*condition: service_started/frontend:\n        condition: service_healthy/g" docker-compose.yml
fi

echo ""
echo "Aplicando correções (docker compose down/up)..."
docker compose down
docker compose up -d

echo ""
echo "Aguardando 15 segundos..."
sleep 15

echo ""
echo "Status dos containers:"
docker ps --filter "name=ai_saas_frontend_prod\|ai_saas_proxy" --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "Teste de conectividade:"
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" http://localhost || echo "Erro ao conectar"

echo ""
echo "✅ Correção aplicada"
'

# Converter para array
IFS=$'\n' read -d '' -r -a SCRIPTS_ARRAY <<< "$APPLY_SCRIPT" || true

OUTPUT=$(az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "${SCRIPTS_ARRAY[@]}" \
    --output json 2>&1)

echo "$OUTPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        print(msg)
except:
    print(sys.stdin.read())
" 2>/dev/null || echo "$OUTPUT"

