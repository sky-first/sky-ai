#!/bin/bash
# Script que aguarda comando anterior terminar e então reinicia o frontend

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
echo -e "${CYAN}    Aguardando e Reiniciando Frontend${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Função para tentar executar comando
try_execute() {
    local max_wait=300  # 5 minutos máximo
    local wait_interval=10  # Verificar a cada 10 segundos
    local elapsed=0
    
    while [ $elapsed -lt $max_wait ]; do
        echo -e "${BLUE} Tentando executar comando... (${elapsed}s/${max_wait}s)${NC}"
        
        local result=$(az vm run-command invoke \
            --resource-group "$RESOURCE_GROUP" \
            --name "$VM_NAME" \
            --command-id RunShellScript \
            --scripts "$@" \
            --output json 2>&1)
        
        if echo "$result" | grep -q "Conflict"; then
            echo -e "${YELLOW} Comando anterior ainda em execução. Aguardando ${wait_interval}s...${NC}"
            sleep $wait_interval
            elapsed=$((elapsed + wait_interval))
        else
            # Sucesso - extrair e mostrar resultado
            echo "$result" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        msg = msg.replace('[stdout]', '').replace('[stderr]', '')
        print(msg)
except:
    print(result)
" 2>/dev/null || echo "$result"
            return 0
        fi
    done
    
    echo -e "${RED}[ERROR] Timeout: Não foi possível executar após ${max_wait} segundos${NC}"
    return 1
}

echo -e "${BLUE}1. Verificando status atual do frontend...${NC}"
try_execute 'docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Names}}: {{.Status}}"'
echo ""

echo -e "${BLUE}2. Verificando logs atuais...${NC}"
try_execute 'docker logs ai_saas_frontend_prod --tail 15'
echo ""

echo -e "${YELLOW}3. Reiniciando frontend...${NC}"
try_execute 'docker restart ai_saas_frontend_prod && echo "[OK] Frontend reiniciado com sucesso"'
echo ""

echo -e "${BLUE}4. Aguardando 25 segundos para o Next.js iniciar...${NC}"
sleep 25
echo ""

echo -e "${BLUE}5. Verificando status após reinício...${NC}"
try_execute 'docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Names}}: {{.Status}}"'
echo ""

echo -e "${BLUE}6. Verificando logs após reinício...${NC}"
try_execute 'docker logs ai_saas_frontend_prod --tail 30'
echo ""

echo -e "${BLUE}7. Testando porta 3000 (dentro do container)...${NC}"
PORT_RESULT=$(try_execute 'docker exec ai_saas_frontend_prod sh -c "wget -qO- --timeout=5 http://localhost:3000 2>&1 | head -3 || echo ERRO_HTTP"' 2>&1)
if echo "$PORT_RESULT" | grep -qE "ERRO_HTTP|timeout|Connection refused"; then
    echo -e "${RED}[ERROR] Frontend ainda não está respondendo na porta 3000${NC}"
    echo "$PORT_RESULT"
else
    echo -e "${GREEN}[OK] Frontend está respondendo!${NC}"
    echo "$PORT_RESULT" | head -3
fi
echo ""

echo -e "${BLUE}8. Testando conectividade nginx -> frontend...${NC}"
NGINX_RESULT=$(try_execute 'docker exec ai_saas_proxy wget -qO- --timeout=5 http://frontend:3000 2>&1 | head -3 || echo ERRO_NGINX' 2>&1)
if echo "$NGINX_RESULT" | grep -qE "ERRO_NGINX|timeout|Connection refused"; then
    echo -e "${RED}[ERROR] Nginx ainda não consegue conectar ao frontend${NC}"
    echo "$NGINX_RESULT"
else
    echo -e "${GREEN}[OK] Nginx consegue conectar ao frontend!${NC}"
    echo "$NGINX_RESULT" | head -3
fi
echo ""

echo -e "${BLUE}9. Verificando recursos do container...${NC}"
try_execute 'docker stats ai_saas_frontend_prod --no-stream --format "CPU: {{.CPUPerc}}, Memória: {{.MemUsage}}"'
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    Resumo${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

if echo "$PORT_RESULT" | grep -qE "ERRO_HTTP|timeout|Connection refused"; then
    echo -e "${YELLOW}[WARNING] Frontend pode estar ainda compilando${NC}"
    echo ""
    echo -e "${BLUE}[INFO] Próximos passos:${NC}"
    echo "   1. Aguarde mais alguns minutos (Next.js pode demorar para compilar)"
    echo "   2. Verifique os logs: docker logs ai_saas_frontend_prod -f"
    echo "   3. Se persistir, verifique recursos: docker stats ai_saas_frontend_prod"
else
    echo -e "${GREEN}[OK] Frontend está respondendo!${NC}"
    echo ""
    echo -e "${BLUE}[INFO] Teste acessando: http://20.185.60.67/dashboard${NC}"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

