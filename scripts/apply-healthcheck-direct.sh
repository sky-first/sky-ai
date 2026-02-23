#!/bin/bash
# Script direto para aplicar healthcheck via Azure CLI
set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

echo " Aplicando healthcheck na VM..."
echo ""

# Script completo em uma única chamada
APPLY_SCRIPT='#!/bin/bash
set -eu

cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || {
    echo "[ERROR] Diretório não encontrado"
    exit 1
}

echo "📁 Diretório: $(pwd)"
echo ""

# Verificar se healthcheck já existe
if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo "[OK] Healthcheck já existe no docker-compose.yml"
else
    echo "[WARNING] Aplicando healthcheck..."
    
    # Fazer backup
    cp docker-compose.yml docker-compose.yml.backup.$(date +%Y%m%d_%H%M%S)
    
    # Adicionar healthcheck usando sed - encontrar linha com "- ai_saas_network" e adicionar após
    sed -i "/- ai_saas_network/a\\
    # Healthcheck para garantir que Next.js está pronto antes de nginx iniciar\\
    # start_period: 90s dá tempo para Next.js compilar em modo dev\\
    healthcheck:\\
      test: [\"CMD\", \"wget\", \"--quiet\", \"--tries=1\", \"--spider\", \"http://localhost:3000/ || exit 1\"]\\
      interval: 30s\\
      timeout: 10s\\
      retries: 5\\
      start_period: 90s" docker-compose.yml
    
    # Verificar se foi aplicado
    if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
        echo "[OK] Healthcheck aplicado com sucesso"
        grep -A 10 "frontend:" docker-compose.yml | grep -A 5 "healthcheck:" | head -6
    else
        echo "[ERROR] Erro ao aplicar healthcheck"
        exit 1
    fi
fi

echo ""
echo " Verificando depends_on do proxy..."
if grep -A 5 "proxy:" docker-compose.yml | grep -A 3 "depends_on:" | grep -q "service_healthy"; then
    echo "[OK] depends_on já usa service_healthy"
else
    echo "[WARNING] Ajustando depends_on..."
    sed -i "s/condition: service_started/condition: service_healthy/g" docker-compose.yml
fi

echo ""
echo "🔄 Aplicando correções (docker compose down/up)..."
docker compose down
echo ""
docker compose up -d
echo ""

echo "⏳ Aguardando 20 segundos para containers iniciarem..."
sleep 20

echo ""
echo "📊 Status dos containers:"
docker ps --filter "name=ai_saas_frontend_prod\|ai_saas_proxy" --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "🧪 Teste de conectividade:"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "000")
echo "  HTTP Status: $HTTP_CODE"

if echo "$HTTP_CODE" | grep -qE "200|301|302|307"; then
    echo "  [OK] Nginx respondendo corretamente"
else
    echo "  [WARNING] Nginx ainda não está respondendo (pode estar inicializando)"
fi

echo ""
echo "📋 Logs do frontend (últimas 5 linhas):"
docker logs ai_saas_frontend_prod --tail 5 2>&1 | tail -3

echo ""
echo "📋 Logs do nginx (últimas 5 linhas):"
docker logs ai_saas_proxy --tail 5 2>&1 | tail -3

echo ""
echo "[OK] Correção aplicada e containers reiniciados"
'

# Converter para array (cada linha é um elemento)
IFS=$'\n' read -d '' -r -a SCRIPTS_ARRAY <<< "$APPLY_SCRIPT" || true

echo "Executando na VM (isso pode levar 2-3 minutos)..."
echo ""

OUTPUT=$(az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "${SCRIPTS_ARRAY[@]}" \
    --output json 2>&1)

# Processar output
if echo "$OUTPUT" | grep -q "Conflict"; then
    echo "[WARNING] Comando anterior ainda em execução. Aguarde alguns minutos e tente novamente."
    exit 1
fi

echo "$OUTPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        msg = msg.replace('[stdout]', '').replace('[stderr]', '')
        print(msg)
    else:
        print('Resposta vazia do Azure CLI')
except json.JSONDecodeError:
    print('Erro ao processar JSON')
    print(sys.stdin.read())
except Exception as e:
    print(f'Erro: {e}')
" 2>/dev/null || echo "$OUTPUT"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "[OK] Deploy concluído"
echo "═══════════════════════════════════════════════════════════"
