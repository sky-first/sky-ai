#!/bin/bash
# Script para verificar status claro de todos os containers

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
echo -e "${CYAN}   🔍 Verificação Completa dos Containers${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Função para executar comando na VM
run_vm_command() {
    az vm run-command invoke \
        --resource-group "$RESOURCE_GROUP" \
        --name "$VM_NAME" \
        --command-id RunShellScript \
        --scripts "$@" \
        --output json 2>&1 | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        msg = msg.replace('[stdout]', '').replace('[stderr]', '')
        print(msg)
except:
    pass
" 2>/dev/null || echo ""
}

echo -e "${BLUE}1. TODOS OS CONTAINERS (status completo):${NC}"
echo ""
ALL_CONTAINERS=$(run_vm_command 'docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
echo "$ALL_CONTAINERS"
echo ""

echo -e "${BLUE}2. CONTAINERS CRÍTICOS (verificação detalhada):${NC}"
echo ""

# PostgreSQL
echo -n "  📊 PostgreSQL (ai_saas_postgres_prod): "
PG_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_postgres_prod" --format "{{.Status}}"')
if [ -n "$PG_STATUS" ]; then
    echo -e "${GREEN}[OK] $PG_STATUS${NC}"
else
    echo -e "${RED}[ERROR] NÃO ESTÁ RODANDO${NC}"
fi

# Redis
echo -n "  📊 Redis (ai_saas_redis_prod): "
REDIS_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_redis_prod" --format "{{.Status}}"')
if [ -n "$REDIS_STATUS" ]; then
    echo -e "${GREEN}[OK] $REDIS_STATUS${NC}"
else
    echo -e "${RED}[ERROR] NÃO ESTÁ RODANDO${NC}"
fi

# Backend
echo -n "  📊 Backend (ai_saas_backend_prod): "
BACKEND_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_backend_prod" --format "{{.Status}}"')
if [ -n "$BACKEND_STATUS" ]; then
    echo -e "${GREEN}[OK] $BACKEND_STATUS${NC}"
else
    echo -e "${RED}[ERROR] NÃO ESTÁ RODANDO${NC}"
fi

# Frontend
echo -n "  📊 Frontend (ai_saas_frontend_prod): "
FRONTEND_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Status}}"')
if [ -n "$FRONTEND_STATUS" ]; then
    echo -e "${GREEN}[OK] $FRONTEND_STATUS${NC}"
else
    echo -e "${RED}[ERROR] NÃO ESTÁ RODANDO${NC}"
fi

# Nginx/Proxy (CRÍTICO - expõe porta 80)
echo -n "  📊 Nginx/Proxy (ai_saas_proxy): "
PROXY_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_proxy" --format "{{.Status}}"')
if [ -n "$PROXY_STATUS" ]; then
    echo -e "${GREEN}[OK] $PROXY_STATUS${NC}"
else
    echo -e "${RED}[ERROR] NÃO ESTÁ RODANDO - ESTE É O PROBLEMA!${NC}"
fi

echo ""
echo -e "${BLUE}3. PORTAS EXPOSTAS (verificação crítica):${NC}"
echo ""
PORTS=$(run_vm_command 'docker ps --format "{{.Names}}\t{{.Ports}}" | grep -E "(80|443|3000|8000)"')
if [ -n "$PORTS" ]; then
    echo "$PORTS"
else
    echo -e "${RED}[ERROR] Nenhuma porta crítica encontrada!${NC}"
fi
echo ""

echo -e "${BLUE}4. VERIFICAÇÃO ESPECÍFICA DO NGINX/PROXY:${NC}"
echo ""
echo -n "  Container existe e está rodando? "
PROXY_EXISTS=$(run_vm_command 'docker ps --filter "name=ai_saas_proxy" --format "{{.Names}}"')
if [ -n "$PROXY_EXISTS" ]; then
    echo -e "${GREEN}[OK] Sim${NC}"
else
    echo -e "${RED}[ERROR] Não${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Tentando iniciar o proxy...${NC}"
    run_vm_command 'cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null && docker compose up -d proxy || docker restart ai_saas_proxy || echo "ERRO_AO_INICIAR"'
    echo ""
    sleep 5
    PROXY_EXISTS=$(run_vm_command 'docker ps --filter "name=ai_saas_proxy" --format "{{.Names}}"')
    if [ -n "$PROXY_EXISTS" ]; then
        echo -e "${GREEN}[OK] Proxy iniciado com sucesso!${NC}"
    else
        echo -e "${RED}[ERROR] Falha ao iniciar proxy${NC}"
    fi
fi

echo ""
echo -n "  Porta 80 está mapeada? "
PORT_80=$(run_vm_command 'docker ps --filter "name=ai_saas_proxy" --format "{{.Ports}}" | grep -o "0.0.0.0:80"')
if [ -n "$PORT_80" ]; then
    echo -e "${GREEN}[OK] Sim (0.0.0.0:80)${NC}"
else
    echo -e "${RED}[ERROR] Não${NC}"
fi

echo ""
echo -n "  Nginx está escutando na porta 80? "
NGINX_LISTEN=$(run_vm_command 'docker exec ai_saas_proxy netstat -tlnp 2>/dev/null | grep ":80 " || docker exec ai_saas_proxy ss -tlnp 2>/dev/null | grep ":80 " || echo "COMANDO_NAO_DISPONIVEL"')
if echo "$NGINX_LISTEN" | grep -q ":80 "; then
    echo -e "${GREEN}[OK] Sim${NC}"
    echo "    $NGINX_LISTEN"
else
    echo -e "${RED}[ERROR] Não ou comando não disponível${NC}"
fi

echo ""
echo -n "  Processo nginx está rodando? "
NGINX_PROCESS=$(run_vm_command 'docker exec ai_saas_proxy ps aux | grep nginx | grep -v grep || echo "NAO_ENCONTRADO"')
if echo "$NGINX_PROCESS" | grep -q "nginx"; then
    echo -e "${GREEN}[OK] Sim${NC}"
else
    echo -e "${RED}[ERROR] Não${NC}"
fi

echo ""
echo -e "${BLUE}5. TESTE DE CONECTIVIDADE EXTERNA:${NC}"
echo ""
echo -n "  Teste localhost:80 (dentro da VM): "
LOCAL_TEST=$(run_vm_command 'curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "ERRO"')
if echo "$LOCAL_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}[OK] Respondeu: HTTP $LOCAL_TEST${NC}"
else
    echo -e "${RED}[ERROR] Não respondeu: $LOCAL_TEST${NC}"
fi

echo ""
echo -n "  Teste do IP da VM (20.185.60.67:80): "
IP_TEST=$(run_vm_command 'curl -s -o /dev/null -w "%{http_code}" http://20.185.60.67 2>&1 || echo "ERRO"')
if echo "$IP_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}[OK] Respondeu: HTTP $IP_TEST${NC}"
else
    echo -e "${RED}[ERROR] Não respondeu: $IP_TEST${NC}"
fi

echo ""
echo -e "${BLUE}6. LOGS DO NGINX (últimas 15 linhas):${NC}"
echo ""
NGINX_LOGS=$(run_vm_command 'docker logs ai_saas_proxy --tail 15 2>&1')
echo "$NGINX_LOGS" | tail -15
echo ""

echo -e "${BLUE}7. VERIFICAÇÃO DE FIREWALL/NSG:${NC}"
echo ""
echo "  Verificando regras de firewall na VM..."
FIREWALL=$(run_vm_command 'sudo iptables -L -n 2>/dev/null | grep -E "(80|443)" | head -5 || echo "IPTABLES_NAO_DISPONIVEL"')
if [ -n "$FIREWALL" ] && ! echo "$FIREWALL" | grep -q "IPTABLES_NAO_DISPONIVEL"; then
    echo "$FIREWALL"
else
    echo -e "${YELLOW}[WARNING] Não foi possível verificar iptables (pode ser normal)${NC}"
    echo -e "${YELLOW}[INFO] Verifique as regras NSG no Azure Portal para portas 80 e 443${NC}"
fi
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   📊 RESUMO${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Verificar se proxy está rodando
if [ -z "$PROXY_EXISTS" ]; then
    echo -e "${RED}[ERROR] PROBLEMA CRÍTICO: Nginx/Proxy não está rodando!${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Solução:${NC}"
    echo "   docker compose up -d proxy"
    echo "   ou"
    echo "   docker restart ai_saas_proxy"
    echo ""
elif [ -z "$PORT_80" ]; then
    echo -e "${RED}[ERROR] PROBLEMA: Porta 80 não está mapeada!${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Verifique o docker-compose.yml${NC}"
    echo ""
elif echo "$LOCAL_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}[OK] Containers estão rodando e nginx responde localmente${NC}"
    echo ""
    if echo "$IP_TEST" | grep -qE "200|301|302|404"; then
        echo -e "${GREEN}[OK] Nginx também responde pelo IP externo${NC}"
    else
        echo -e "${YELLOW}[WARNING] Nginx não responde pelo IP externo - pode ser problema de NSG/Firewall${NC}"
        echo ""
        echo -e "${BLUE}[INFO] Verifique no Azure Portal:${NC}"
        echo "   1. Network Security Group (NSG) da VM"
        echo "   2. Regras de entrada para portas 80 e 443"
        echo "   3. Firewall do Azure"
    fi
else
    echo -e "${RED}[ERROR] Nginx não está respondendo${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Verifique os logs acima${NC}"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

