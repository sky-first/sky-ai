#!/bin/bash
# Script para corrigir erro 502 Bad Gateway do frontend
# Reinicia o frontend e verifica status

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
echo -e "${CYAN}    Correção do Erro 502 Bad Gateway${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Função para executar comando na VM
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
                echo -e "${YELLOW}⏳ Comando anterior ainda em execução. Aguardando... (tentativa $attempt/$max_attempts)${NC}"
                sleep 10
                attempt=$((attempt + 1))
            else
                echo -e "${RED}[ERROR] Timeout: Comando anterior ainda em execução após $max_attempts tentativas${NC}"
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
}

echo -e "${BLUE}1. Verificando status atual do frontend...${NC}"
CURRENT_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Names}}: {{.Status}}"')
echo "$CURRENT_STATUS"
echo ""

echo -e "${BLUE}2. Verificando logs antes do reinício...${NC}"
BEFORE_LOGS=$(run_vm_command 'docker logs ai_saas_frontend_prod --tail 15 2>&1')
echo "$BEFORE_LOGS" | tail -15
echo ""

echo -e "${YELLOW}3. Reiniciando frontend...${NC}"
RESTART_RESULT=$(run_vm_command 'docker restart ai_saas_frontend_prod && echo "[OK] Frontend reiniciado"')
echo "$RESTART_RESULT"
echo ""

echo -e "${BLUE}4. Aguardando frontend iniciar (20 segundos)...${NC}"
sleep 20
echo ""

echo -e "${BLUE}5. Verificando status após reinício...${NC}"
AFTER_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Names}}: {{.Status}}"')
echo "$AFTER_STATUS"
echo ""

echo -e "${BLUE}6. Verificando logs após reinício...${NC}"
AFTER_LOGS=$(run_vm_command 'docker logs ai_saas_frontend_prod --tail 30 2>&1')
echo "$AFTER_LOGS" | tail -30
echo ""

echo -e "${BLUE}7. Testando porta 3000 (dentro do container)...${NC}"
PORT_TEST=$(run_vm_command 'docker exec ai_saas_frontend_prod sh -c "wget -qO- --timeout=5 http://localhost:3000 2>&1 | head -3 || echo ERRO_HTTP"' 2>&1 || echo "ERRO_TESTE")
if echo "$PORT_TEST" | grep -qE "ERRO_HTTP|ERRO_TESTE|timeout|Connection refused"; then
    echo -e "${RED}[ERROR] Frontend ainda não está respondendo na porta 3000${NC}"
    echo "$PORT_TEST"
else
    echo -e "${GREEN}[OK] Frontend está respondendo!${NC}"
    echo "$PORT_TEST" | head -3
fi
echo ""

echo -e "${BLUE}8. Testando conectividade nginx -> frontend...${NC}"
NGINX_TEST=$(run_vm_command 'docker exec ai_saas_proxy wget -qO- --timeout=5 http://frontend:3000 2>&1 | head -3 || echo ERRO_NGINX')
if echo "$NGINX_TEST" | grep -qE "ERRO_NGINX|timeout|Connection refused"; then
    echo -e "${RED}[ERROR] Nginx ainda não consegue conectar ao frontend${NC}"
    echo "$NGINX_TEST"
else
    echo -e "${GREEN}[OK] Nginx consegue conectar ao frontend!${NC}"
    echo "$NGINX_TEST" | head -3
fi
echo ""

echo -e "${BLUE}9. Verificando recursos do container...${NC}"
STATS=$(run_vm_command 'docker stats ai_saas_frontend_prod --no-stream --format "CPU: {{.CPUPerc}}, Memória: {{.MemUsage}}"')
echo "$STATS"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   📊 Resumo${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

if echo "$PORT_TEST" | grep -qE "ERRO_HTTP|ERRO_TESTE|timeout|Connection refused"; then
    echo -e "${RED}[ERROR] Frontend ainda não está respondendo${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Próximos passos:${NC}"
    echo "   1. Verificar se há erros nos logs acima"
    echo "   2. Verificar recursos do sistema (memória/CPU)"
    echo "   3. Verificar se o Next.js está compilando (pode demorar)"
    echo "   4. Tentar rebuild do container:"
    echo "      docker compose up -d --build frontend"
else
    echo -e "${GREEN}[OK] Frontend está respondendo!${NC}"
    echo ""
    echo -e "${BLUE}[INFO] Teste acessando: http://20.185.60.67/dashboard${NC}"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

