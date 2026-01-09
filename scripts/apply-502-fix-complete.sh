#!/bin/bash
# Script completo e robusto para aplicar correção 502 com validação total
set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

echo "═══════════════════════════════════════════════════════════"
echo "🚀 APLICAÇÃO COMPLETA DA CORREÇÃO 502 BAD GATEWAY"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Função para aguardar comandos anteriores finalizarem
wait_for_previous_command() {
    local max_wait=300
    local waited=0
    
    echo "⏳ Aguardando comandos anteriores finalizarem..."
    while [ $waited -lt $max_wait ]; do
        if az vm run-command invoke \
            --resource-group "$RESOURCE_GROUP" \
            --name "$VM_NAME" \
            --command-id RunShellScript \
            --scripts 'echo "test"' \
            --output json 2>&1 | grep -q "Conflict"; then
            echo "  Aguardando... ($waited segundos)"
            sleep 10
            waited=$((waited + 10))
        else
            echo "✅ Comandos anteriores finalizados"
            return 0
        fi
    done
    
    echo "⚠️  Timeout aguardando comandos anteriores"
    return 1
}

# Aguardar comandos anteriores
wait_for_previous_command

echo ""
echo "📋 PASSO 1: Verificando estado atual..."
echo ""

# Verificar estado atual
CHECK_SCRIPT='#!/bin/bash
set -eu
cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || exit 1

echo "=== Estado Atual ==="
echo ""
echo "1. Healthcheck no docker-compose.yml:"
if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo "   ✅ Healthcheck JÁ EXISTE"
    grep -A 10 "frontend:" docker-compose.yml | grep -A 5 "healthcheck:" | head -6
else
    echo "   ❌ Healthcheck NÃO encontrado"
fi

echo ""
echo "2. Status dos containers:"
docker ps --filter "name=frontend\|proxy" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "   Nenhum container rodando"

echo ""
echo "3. Teste HTTP:"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "000")
echo "   HTTP Status: $HTTP_CODE"
'

IFS=$'\n' read -d '' -r -a CHECK_ARRAY <<< "$CHECK_SCRIPT" || true

echo "Executando verificação inicial..."
az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "${CHECK_ARRAY[@]}" \
    --output json 2>&1 | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        print(msg.replace('[stdout]', '').replace('[stderr]', ''))
except:
    pass
" 2>/dev/null || echo "Verificação executada"

echo ""
echo "📋 PASSO 2: Aplicando healthcheck..."
echo ""

# Script completo para aplicar healthcheck
APPLY_SCRIPT='#!/bin/bash
set -eu

cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || {
    echo "❌ Diretório não encontrado"
    exit 1
}

echo "📁 Diretório: $(pwd)"
echo ""

# Verificar se healthcheck já existe
if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo "✅ Healthcheck já existe - pulando aplicação"
else
    echo "⚠️  Aplicando healthcheck..."
    
    # Fazer backup
    BACKUP_FILE="docker-compose.yml.backup.$(date +%Y%m%d_%H%M%S)"
    cp docker-compose.yml "$BACKUP_FILE"
    echo "✅ Backup criado: $BACKUP_FILE"
    
    # Criar arquivo temporário com healthcheck
    cat > /tmp/healthcheck_block.txt << 'HEALTHCHECK_EOF'
    # Healthcheck para garantir que Next.js está pronto antes de nginx iniciar
    # start_period: 90s dá tempo para Next.js compilar em modo dev (NODE_ENV=development)
    # Isso elimina race condition: nginx só inicia quando frontend está realmente pronto
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:3000/ || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 90s
HEALTHCHECK_EOF
    
    # Usar awk para inserir após a linha com "- ai_saas_network" no serviço frontend
    awk '
    /^  frontend:/ { in_frontend=1; print; next }
    in_frontend && /- ai_saas_network/ { 
        print
        while ((getline line < "/tmp/healthcheck_block.txt") > 0) {
            print line
        }
        close("/tmp/healthcheck_block.txt")
        in_frontend=0
        next
    }
    in_frontend && /^  [a-z]/ { in_frontend=0 }
    { print }
    ' docker-compose.yml > docker-compose.yml.new
    
    if [ $? -eq 0 ] && [ -f docker-compose.yml.new ]; then
        mv docker-compose.yml.new docker-compose.yml
        echo "✅ Healthcheck aplicado usando awk"
    else
        # Fallback: usar sed
        echo "⚠️  Tentando método alternativo (sed)..."
        sed -i "/- ai_saas_network/a\\
    # Healthcheck para garantir que Next.js está pronto\\
    healthcheck:\\
      test: [\"CMD\", \"wget\", \"--quiet\", \"--tries=1\", \"--spider\", \"http://localhost:3000/ || exit 1\"]\\
      interval: 30s\\
      timeout: 10s\\
      retries: 5\\
      start_period: 90s" docker-compose.yml
    fi
    
    # Validar que foi aplicado
    if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
        echo "✅ Healthcheck aplicado e validado"
        echo ""
        echo "Conteúdo aplicado:"
        grep -A 10 "frontend:" docker-compose.yml | grep -A 5 "healthcheck:" | head -6
    else
        echo "❌ ERRO: Healthcheck não foi aplicado corretamente"
        echo "Restaurando backup..."
        mv "$BACKUP_FILE" docker-compose.yml
        exit 1
    fi
fi

echo ""
echo "🔧 Verificando depends_on do proxy..."
if grep -A 5 "proxy:" docker-compose.yml | grep -A 3 "depends_on:" | grep -q "service_healthy"; then
    echo "✅ depends_on já usa service_healthy"
else
    echo "⚠️  Ajustando depends_on para service_healthy..."
    sed -i "s/condition: service_started/condition: service_healthy/g" docker-compose.yml
    echo "✅ depends_on ajustado"
fi

echo ""
echo "🔄 Aplicando correções (docker compose down/up)..."
docker compose down
echo ""
echo "Iniciando containers..."
docker compose up -d
echo ""
echo "✅ Containers reiniciados"
'

IFS=$'\n' read -d '' -r -a APPLY_ARRAY <<< "$APPLY_SCRIPT" || true

echo "Executando aplicação do healthcheck..."
az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "${APPLY_ARRAY[@]}" \
    --output json 2>&1 | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        print(msg.replace('[stdout]', '').replace('[stderr]', ''))
except:
    pass
" 2>/dev/null || echo "Aplicação executada"

echo ""
echo "⏳ Aguardando 30 segundos para containers iniciarem..."
sleep 30

echo ""
echo "📋 PASSO 3: Validação completa..."
echo ""

# Script de validação completa
VALIDATE_SCRIPT='#!/bin/bash
set -eu

cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || exit 1

echo "=== VALIDAÇÃO COMPLETA ==="
echo ""

# 1. Verificar healthcheck
echo "1. Healthcheck no docker-compose.yml:"
if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo "   ✅ Healthcheck CONFIRMADO"
    grep -A 10 "frontend:" docker-compose.yml | grep -A 5 "healthcheck:" | head -6 | sed "s/^/   /"
else
    echo "   ❌ Healthcheck NÃO encontrado"
    exit 1
fi

echo ""
echo "2. Status dos containers:"
docker ps --filter "name=frontend\|proxy" --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "3. Verificando healthcheck do frontend:"
FRONTEND_STATUS=$(docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Status}}" 2>/dev/null || echo "NOT_RUNNING")
echo "   Frontend: $FRONTEND_STATUS"

if echo "$FRONTEND_STATUS" | grep -q "healthy"; then
    echo "   ✅ Frontend está HEALTHY"
    FRONTEND_HEALTHY=true
elif echo "$FRONTEND_STATUS" | grep -q "unhealthy"; then
    echo "   ⚠️  Frontend está UNHEALTHY (pode estar compilando)"
    FRONTEND_HEALTHY=false
elif echo "$FRONTEND_STATUS" | grep -q "Up"; then
    echo "   ⚠️  Frontend está UP mas ainda não healthy (aguardando healthcheck)"
    FRONTEND_HEALTHY=false
else
    echo "   ❌ Frontend não está rodando"
    FRONTEND_HEALTHY=false
fi

echo ""
echo "4. Testes de conectividade:"
echo -n "   localhost:80: "
HTTP_LOCAL=$(curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "000")
if echo "$HTTP_LOCAL" | grep -qE "200|301|302|307"; then
    echo "✅ HTTP $HTTP_LOCAL"
    HTTP_OK=true
else
    echo "❌ HTTP $HTTP_LOCAL"
    HTTP_OK=false
fi

echo -n "   nginx → frontend: "
HTTP_NGINX=$(docker exec ai_saas_proxy curl -s -o /dev/null -w "%{http_code}" http://frontend:3000 2>&1 || echo "000")
if echo "$HTTP_NGINX" | grep -qE "200|301|302|307"; then
    echo "✅ HTTP $HTTP_NGINX"
    NGINX_OK=true
else
    echo "❌ HTTP $HTTP_NGINX"
    NGINX_OK=false
fi

echo -n "   IP externo (20.185.60.67): "
HTTP_EXTERNAL=$(curl -s -o /dev/null -w "%{http_code}" http://20.185.60.67 2>&1 || echo "000")
if echo "$HTTP_EXTERNAL" | grep -qE "200|301|302|307"; then
    echo "✅ HTTP $HTTP_EXTERNAL"
    EXTERNAL_OK=true
else
    echo "❌ HTTP $HTTP_EXTERNAL"
    EXTERNAL_OK=false
fi

echo ""
echo "5. Verificando logs do nginx (últimas 20 linhas):"
NGINX_LOGS=$(docker logs ai_saas_proxy --tail 20 2>&1)
if echo "$NGINX_LOGS" | grep -q "502\|Connection refused.*frontend"; then
    echo "   ⚠️  Ainda há erros 502 nos logs"
    echo "$NGINX_LOGS" | grep -i "502\|refused" | tail -5 | sed "s/^/   /"
    NO_502=false
else
    echo "   ✅ Nenhum erro 502 encontrado nos logs"
    NO_502=true
fi

echo ""
echo "=== RESUMO ==="
CRITERIA_MET=0
TOTAL_CRITERIA=5

if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo "✅ 1. Healthcheck aplicado"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo "❌ 1. Healthcheck não aplicado"
fi

if [ "$FRONTEND_HEALTHY" = true ]; then
    echo "✅ 2. Frontend está healthy"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo "⚠️  2. Frontend ainda não está healthy (pode estar compilando)"
fi

if [ "$HTTP_OK" = true ]; then
    echo "✅ 3. Nginx respondendo corretamente"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo "❌ 3. Nginx não está respondendo"
fi

if [ "$NO_502" = true ]; then
    echo "✅ 4. Nenhum 502 nos logs"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo "⚠️  4. Ainda há 502 nos logs"
fi

if [ "$EXTERNAL_OK" = true ]; then
    echo "✅ 5. Sistema acessível externamente"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo "⚠️  5. Sistema não acessível externamente"
fi

echo ""
echo "Resultado: $CRITERIA_MET/$TOTAL_CRITERIA critérios atendidos"

if [ $CRITERIA_MET -eq $TOTAL_CRITERIA ]; then
    echo ""
    echo "✅✅✅ TODOS OS CRITÉRIOS ATENDIDOS - CORREÇÃO APLICADA COM SUCESSO"
    exit 0
elif [ $CRITERIA_MET -ge 3 ]; then
    echo ""
    echo "⚠️  Correção aplicada parcialmente - aguardar mais tempo para frontend compilar"
    exit 0
else
    echo ""
    echo "❌ Correção não foi aplicada corretamente"
    exit 1
fi
'

IFS=$'\n' read -d '' -r -a VALIDATE_ARRAY <<< "$VALIDATE_SCRIPT" || true

echo "Executando validação completa..."
az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "${VALIDATE_ARRAY[@]}" \
    --output json 2>&1 | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        print(msg.replace('[stdout]', '').replace('[stderr]', ''))
except:
    pass
" 2>/dev/null || echo "Validação executada"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ PROCESSO COMPLETO FINALIZADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "💡 Verifique o output acima para confirmar o status"
echo "🌐 Teste acessando: http://20.185.60.67"
echo ""

