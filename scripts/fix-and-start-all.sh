#!/bin/bash
# Script assertivo para verificar e iniciar todos os containers necessários

set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   🔧 Verificação e Correção Assertiva${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Função para executar comando
run_vm_command() {
    local max_attempts=5
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        local result=$(az vm run-command invoke \
            --resource-group "$RESOURCE_GROUP" \
            --name "$VM_NAME" \
            --command-id RunShellScript \
            --scripts "$@" \
            --output json 2>&1)
        
        if echo "$result" | grep -q "Conflict"; then
            if [ $attempt -lt $max_attempts ]; then
                sleep 10
                attempt=$((attempt + 1))
            else
                echo "TIMEOUT"
                return 1
            fi
        else
            echo "$result" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        msg = msg.replace('[stdout]', '').replace('[stderr]', '')
        print(msg)
except:
    pass
" 2>/dev/null || echo "$result"
            return 0
        fi
    done
    return 1
}

echo -e "${BLUE}1️⃣ Verificando status atual...${NC}"
STATUS=$(run_vm_command 'docker ps -a --format "{{.Names}}:{{.Status}}" | head -15')
echo "$STATUS"
echo ""

echo -e "${BLUE}2️⃣ Identificando containers parados...${NC}"
STOPPED=$(run_vm_command 'docker ps -a --filter "status=exited" --format "{{.Names}}"')
if [ -n "$STOPPED" ]; then
    echo "Containers parados encontrados:"
    echo "$STOPPED"
    echo ""
    
    echo -e "${YELLOW}3️⃣ Iniciando containers parados...${NC}"
    for container in $STOPPED; do
        if [ -n "$container" ]; then
            echo -n "  Iniciando $container... "
            START_RESULT=$(run_vm_command "docker start $container 2>&1")
            if echo "$START_RESULT" | grep -q "$container"; then
                echo -e "${GREEN}✅${NC}"
            else
                echo -e "${RED}❌${NC}"
                echo "    Erro: $START_RESULT"
            fi
        fi
    done
else
    echo -e "${GREEN}✅ Nenhum container parado${NC}"
fi
echo ""

echo -e "${BLUE}4️⃣ Verificando containers críticos...${NC}"
CRITICAL=("ai_saas_postgres_prod" "ai_saas_redis_prod" "ai_saas_backend_prod" "ai_saas_frontend_prod" "ai_saas_proxy")

for container in "${CRITICAL[@]}"; do
    CONTAINER_STATUS=$(run_vm_command "docker ps --filter 'name=$container' --format '{{.Status}}'")
    if [ -n "$CONTAINER_STATUS" ]; then
        echo -e "  ${GREEN}✅ $container: $CONTAINER_STATUS${NC}"
    else
        echo -e "  ${RED}❌ $container: NÃO ESTÁ RODANDO${NC}"
        echo -e "    ${YELLOW}Iniciando...${NC}"
        run_vm_command "docker start $container 2>&1"
        sleep 3
    fi
done
echo ""

echo -e "${BLUE}5️⃣ Aguardando serviços iniciarem (15 segundos)...${NC}"
sleep 15
echo ""

echo -e "${BLUE}6️⃣ Verificando portas expostas...${NC}"
PORTS=$(run_vm_command 'docker ps --format "{{.Names}}: {{.Ports}}" | grep -E "(80|443|3000|8000)"')
echo "$PORTS"
echo ""

echo -e "${BLUE}7️⃣ Testando conectividade...${NC}"
echo -n "  Nginx localhost:80: "
NGINX_TEST=$(run_vm_command 'curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "ERRO"')
if echo "$NGINX_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}✅ HTTP $NGINX_TEST${NC}"
else
    echo -e "${RED}❌ $NGINX_TEST${NC}"
fi

echo -n "  Backend localhost:8000/health: "
BACKEND_TEST=$(run_vm_command 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>&1 || echo "ERRO"')
if echo "$BACKEND_TEST" | grep -qE "200|301|302"; then
    echo -e "${GREEN}✅ HTTP $BACKEND_TEST${NC}"
else
    echo -e "${RED}❌ $BACKEND_TEST${NC}"
fi

echo -n "  Frontend (via nginx): "
FRONTEND_TEST=$(run_vm_command 'curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "ERRO"')
if echo "$FRONTEND_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}✅ HTTP $FRONTEND_TEST${NC}"
else
    echo -e "${RED}❌ $FRONTEND_TEST${NC}"
fi
echo ""

echo -e "${BLUE}8️⃣ Verificando logs do nginx (últimas 10 linhas)...${NC}"
NGINX_LOGS=$(run_vm_command 'docker logs ai_saas_proxy --tail 10 2>&1')
echo "$NGINX_LOGS" | tail -10
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   📊 RESUMO FINAL${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

FINAL_STATUS=$(run_vm_command 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | head -8')
echo "$FINAL_STATUS"
echo ""

if echo "$NGINX_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}✅ Nginx está respondendo!${NC}"
    echo ""
    echo -e "${BLUE}💡 Teste acessando: http://20.185.60.67${NC}"
    echo ""
    if ! echo "$NGINX_TEST" | grep -qE "200|301|302|404"; then
        echo -e "${YELLOW}⚠️  Se ainda houver ERR_CONNECTION_REFUSED:${NC}"
        echo "   1. Verifique NSG no Azure Portal (portas 80/443)"
        echo "   2. Aguarde 1-2 minutos para propagação"
    fi
else
    echo -e "${RED}❌ Nginx ainda não está respondendo${NC}"
    echo ""
    echo -e "${YELLOW}💡 Verifique:${NC}"
    echo "   - Logs: docker logs ai_saas_proxy"
    echo "   - Status: docker ps | grep proxy"
    echo "   - Portas: docker ps --filter name=proxy --format '{{.Ports}}'"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

