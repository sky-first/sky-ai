#!/bin/bash
# Script completo de validação - entra em cada container e verifica tudo
# Valida status, processos, conectividade, logs e endpoints

set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    Validação Completa dos Containers${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Função para executar comando na VM e extrair output
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
        # Limpar [stdout] e [stderr]
        msg = msg.replace('[stdout]', '').replace('[stderr]', '')
        print(msg)
except:
    pass
" 2>/dev/null || echo ""
}

# ============================================================================
# 1. STATUS GERAL DOS CONTAINERS
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   1. STATUS GERAL DOS CONTAINERS${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

ALL_CONTAINERS=$(run_vm_command 'docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | head -20')
echo "$ALL_CONTAINERS"
echo ""

# ============================================================================
# 2. VALIDAÇÃO DO POSTGRES
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   2. CONTAINER: PostgreSQL (ai_saas_postgres_prod)${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE} Status do container:${NC}"
PG_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_postgres_prod" --format "{{.Status}}"')
if [ -n "$PG_STATUS" ]; then
    echo -e "${GREEN}[OK] Rodando: $PG_STATUS${NC}"
else
    echo -e "${RED}[ERROR] Container não está rodando${NC}"
fi
echo ""

echo -e "${BLUE} Processos dentro do container:${NC}"
PG_PROCESSES=$(run_vm_command 'docker exec ai_saas_postgres_prod ps aux | grep -E "(postgres|PID)" | head -5')
echo "$PG_PROCESSES"
echo ""

echo -e "${BLUE} Porta 5432 escutando:${NC}"
PG_PORT=$(run_vm_command 'docker exec ai_saas_postgres_prod netstat -tlnp 2>/dev/null | grep 5432 || ss -tlnp 2>/dev/null | grep 5432 || echo "Comando não disponível"')
echo "$PG_PORT"
echo ""

echo -e "${BLUE} Health check:${NC}"
PG_HEALTH=$(run_vm_command 'docker exec ai_saas_postgres_prod pg_isready -U postgres')
if echo "$PG_HEALTH" | grep -q "accepting connections"; then
    echo -e "${GREEN}[OK] $PG_HEALTH${NC}"
else
    echo -e "${RED}[ERROR] $PG_HEALTH${NC}"
fi
echo ""

echo -e "${BLUE} Últimas 10 linhas do log:${NC}"
PG_LOGS=$(run_vm_command 'docker logs ai_saas_postgres_prod --tail 10 2>&1')
echo "$PG_LOGS" | tail -10
echo ""

# ============================================================================
# 3. VALIDAÇÃO DO REDIS
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   3. CONTAINER: Redis (ai_saas_redis_prod)${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE} Status do container:${NC}"
REDIS_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_redis_prod" --format "{{.Status}}"')
if [ -n "$REDIS_STATUS" ]; then
    echo -e "${GREEN}[OK] Rodando: $REDIS_STATUS${NC}"
else
    echo -e "${RED}[ERROR] Container não está rodando${NC}"
fi
echo ""

echo -e "${BLUE} Processos dentro do container:${NC}"
REDIS_PROCESSES=$(run_vm_command 'docker exec ai_saas_redis_prod ps aux | grep -E "(redis|PID)" | head -3')
echo "$REDIS_PROCESSES"
echo ""

echo -e "${BLUE} Porta 6379 escutando:${NC}"
REDIS_PORT=$(run_vm_command 'docker exec ai_saas_redis_prod netstat -tlnp 2>/dev/null | grep 6379 || ss -tlnp 2>/dev/null | grep 6379 || echo "Comando não disponível"')
echo "$REDIS_PORT"
echo ""

echo -e "${BLUE} Teste PING:${NC}"
REDIS_PING=$(run_vm_command 'docker exec ai_saas_redis_prod redis-cli ping 2>&1')
if echo "$REDIS_PING" | grep -qE "PONG|NOAUTH"; then
    echo -e "${GREEN}[OK] Redis respondendo${NC}"
else
    echo -e "${RED}[ERROR] Redis não está respondendo: $REDIS_PING${NC}"
fi
echo ""

echo -e "${BLUE} Últimas 10 linhas do log:${NC}"
REDIS_LOGS=$(run_vm_command 'docker logs ai_saas_redis_prod --tail 10 2>&1')
echo "$REDIS_LOGS" | tail -10
echo ""

# ============================================================================
# 4. VALIDAÇÃO DO BACKEND
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   4. CONTAINER: Backend (ai_saas_backend_prod)${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE} Status do container:${NC}"
BACKEND_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_backend_prod" --format "{{.Status}}"')
if [ -n "$BACKEND_STATUS" ]; then
    echo -e "${GREEN}[OK] Rodando: $BACKEND_STATUS${NC}"
else
    echo -e "${RED}[ERROR] Container não está rodando${NC}"
fi
echo ""

echo -e "${BLUE} Processos dentro do container:${NC}"
BACKEND_PROCESSES=$(run_vm_command 'docker exec ai_saas_backend_prod ps aux | head -10')
echo "$BACKEND_PROCESSES"
echo ""

echo -e "${BLUE} Porta 8000 escutando:${NC}"
BACKEND_PORT=$(run_vm_command 'docker exec ai_saas_backend_prod netstat -tlnp 2>/dev/null | grep 8000 || ss -tlnp 2>/dev/null | grep 8000 || echo "Comando não disponível"')
echo "$BACKEND_PORT"
echo ""

echo -e "${BLUE} Teste endpoint /health (dentro do container):${NC}"
BACKEND_HEALTH=$(run_vm_command 'docker exec ai_saas_backend_prod curl -s http://localhost:8000/health 2>&1 | head -5 || echo "ERRO"')
if echo "$BACKEND_HEALTH" | grep -qE "status|ok|healthy"; then
    echo -e "${GREEN}[OK] Backend respondendo:${NC}"
    echo "$BACKEND_HEALTH"
else
    echo -e "${RED}[ERROR] Backend não está respondendo:${NC}"
    echo "$BACKEND_HEALTH"
fi
echo ""

echo -e "${BLUE} Teste conectividade backend -> postgres:${NC}"
BACKEND_TO_PG=$(run_vm_command 'docker exec ai_saas_backend_prod nc -zv postgres 5432 2>&1 || echo "nc não disponível"')
echo "$BACKEND_TO_PG"
echo ""

echo -e "${BLUE} Teste conectividade backend -> redis:${NC}"
BACKEND_TO_REDIS=$(run_vm_command 'docker exec ai_saas_backend_prod nc -zv redis 6379 2>&1 || echo "nc não disponível"')
echo "$BACKEND_TO_REDIS"
echo ""

echo -e "${BLUE} Últimas 20 linhas do log:${NC}"
BACKEND_LOGS=$(run_vm_command 'docker logs ai_saas_backend_prod --tail 20 2>&1')
echo "$BACKEND_LOGS" | tail -20
echo ""

# ============================================================================
# 5. VALIDAÇÃO DO FRONTEND
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   5. CONTAINER: Frontend (ai_saas_frontend_prod)${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE} Status do container:${NC}"
FRONTEND_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Status}}"')
if [ -n "$FRONTEND_STATUS" ]; then
    echo -e "${GREEN}[OK] Rodando: $FRONTEND_STATUS${NC}"
else
    echo -e "${RED}[ERROR] Container não está rodando${NC}"
fi
echo ""

echo -e "${BLUE} Processos dentro do container:${NC}"
FRONTEND_PROCESSES=$(run_vm_command 'docker exec ai_saas_frontend_prod ps aux | head -10')
echo "$FRONTEND_PROCESSES"
echo ""

echo -e "${BLUE} Porta 3000 escutando:${NC}"
FRONTEND_PORT=$(run_vm_command 'docker exec ai_saas_frontend_prod netstat -tlnp 2>/dev/null | grep 3000 || ss -tlnp 2>/dev/null | grep 3000 || echo "Comando não disponível"')
echo "$FRONTEND_PORT"
echo ""

echo -e "${BLUE} Teste endpoint / (dentro do container):${NC}"
FRONTEND_TEST=$(run_vm_command 'docker exec ai_saas_frontend_prod curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3000 2>&1 || echo "ERRO"')
if echo "$FRONTEND_TEST" | grep -qE "200|301|302"; then
    echo -e "${GREEN}[OK] Frontend respondendo: $FRONTEND_TEST${NC}"
else
    echo -e "${RED}[ERROR] Frontend não está respondendo: $FRONTEND_TEST${NC}"
fi
echo ""

echo -e "${BLUE} Teste endpoint /dashboard (dentro do container):${NC}"
FRONTEND_DASHBOARD=$(run_vm_command 'docker exec ai_saas_frontend_prod curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3000/dashboard 2>&1 || echo "ERRO"')
if echo "$FRONTEND_DASHBOARD" | grep -qE "200|301|302"; then
    echo -e "${GREEN}[OK] Dashboard respondendo: $FRONTEND_DASHBOARD${NC}"
else
    echo -e "${RED}[ERROR] Dashboard não está respondendo: $FRONTEND_DASHBOARD${NC}"
fi
echo ""

echo -e "${BLUE} Teste conectividade frontend -> backend:${NC}"
FRONTEND_TO_BACKEND=$(run_vm_command 'docker exec ai_saas_frontend_prod nc -zv backend 8000 2>&1 || echo "nc não disponível"')
echo "$FRONTEND_TO_BACKEND"
echo ""

echo -e "${BLUE} Últimas 30 linhas do log:${NC}"
FRONTEND_LOGS=$(run_vm_command 'docker logs ai_saas_frontend_prod --tail 30 2>&1')
echo "$FRONTEND_LOGS" | tail -30
echo ""

# ============================================================================
# 6. VALIDAÇÃO DO NGINX/PROXY
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   6. CONTAINER: Nginx/Proxy (ai_saas_proxy)${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE} Status do container:${NC}"
PROXY_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_proxy" --format "{{.Status}}"')
if [ -n "$PROXY_STATUS" ]; then
    echo -e "${GREEN}[OK] Rodando: $PROXY_STATUS${NC}"
else
    echo -e "${RED}[ERROR] Container não está rodando${NC}"
fi
echo ""

echo -e "${BLUE} Processos dentro do container:${NC}"
PROXY_PROCESSES=$(run_vm_command 'docker exec ai_saas_proxy ps aux | head -10')
echo "$PROXY_PROCESSES"
echo ""

echo -e "${BLUE} Portas 80 e 443 escutando:${NC}"
PROXY_PORTS=$(run_vm_command 'docker exec ai_saas_proxy netstat -tlnp 2>/dev/null | grep -E "(80|443)" || ss -tlnp 2>/dev/null | grep -E "(80|443)" || echo "Comando não disponível"')
echo "$PROXY_PORTS"
echo ""

echo -e "${BLUE} Teste conectividade nginx -> frontend:${NC}"
PROXY_TO_FRONTEND=$(run_vm_command 'docker exec ai_saas_proxy wget -qO- --timeout=5 http://frontend:3000 2>&1 | head -3 || echo "ERRO_CONEXAO"')
if echo "$PROXY_TO_FRONTEND" | grep -qE "ERRO_CONEXAO|timeout|Connection refused"; then
    echo -e "${RED}[ERROR] Nginx NÃO consegue conectar ao frontend${NC}"
    echo "$PROXY_TO_FRONTEND"
else
    echo -e "${GREEN}[OK] Nginx consegue conectar ao frontend${NC}"
fi
echo ""

echo -e "${BLUE} Teste conectividade nginx -> backend:${NC}"
PROXY_TO_BACKEND=$(run_vm_command 'docker exec ai_saas_proxy wget -qO- --timeout=5 http://backend:8000/health 2>&1 | head -3 || echo "ERRO_CONEXAO"')
if echo "$PROXY_TO_BACKEND" | grep -qE "ERRO_CONEXAO|timeout|Connection refused"; then
    echo -e "${RED}[ERROR] Nginx NÃO consegue conectar ao backend${NC}"
    echo "$PROXY_TO_BACKEND"
else
    echo -e "${GREEN}[OK] Nginx consegue conectar ao backend${NC}"
fi
echo ""

echo -e "${BLUE} Últimas 20 linhas do log (erros):${NC}"
PROXY_LOGS=$(run_vm_command 'docker logs ai_saas_proxy --tail 20 2>&1 | grep -E "(error|502|upstream|frontend|backend)" || docker logs ai_saas_proxy --tail 20 2>&1')
echo "$PROXY_LOGS" | tail -20
echo ""

# ============================================================================
# 7. VALIDAÇÃO DA REDE DOCKER
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   7. REDE DOCKER (ai_saas_network)${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE} Containers na rede:${NC}"
NETWORK_CONTAINERS=$(run_vm_command 'docker network inspect ai_saas_network --format "{{range .Containers}}{{.Name}} ({{.IPv4Address}}){{println}}{{end}}" 2>&1')
echo "$NETWORK_CONTAINERS"
echo ""

echo -e "${BLUE} Configuração da rede:${NC}"
NETWORK_CONFIG=$(run_vm_command 'docker network inspect ai_saas_network --format "Driver: {{.Driver}}, Subnet: {{range .IPAM.Config}}{{.Subnet}}{{end}}" 2>&1')
echo "$NETWORK_CONFIG"
echo ""

# ============================================================================
# 8. TESTES DE CONECTIVIDADE ENTRE CONTAINERS
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   8. TESTES DE CONECTIVIDADE${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE} Frontend -> Backend (http://backend:8000/health):${NC}"
FRONTEND_BACKEND_TEST=$(run_vm_command 'docker exec ai_saas_frontend_prod curl -s -o /dev/null -w "HTTP %{http_code}\n" http://backend:8000/health 2>&1 || echo "ERRO"')
echo "$FRONTEND_BACKEND_TEST"
echo ""

echo -e "${BLUE} Nginx -> Frontend (http://frontend:3000):${NC}"
NGINX_FRONTEND_TEST=$(run_vm_command 'docker exec ai_saas_proxy curl -s -o /dev/null -w "HTTP %{http_code}\n" http://frontend:3000 2>&1 || echo "ERRO"')
echo "$NGINX_FRONTEND_TEST"
echo ""

echo -e "${BLUE} Nginx -> Backend (http://backend:8000/health):${NC}"
NGINX_BACKEND_TEST=$(run_vm_command 'docker exec ai_saas_proxy curl -s -o /dev/null -w "HTTP %{http_code}\n" http://backend:8000/health 2>&1 || echo "ERRO"')
echo "$NGINX_BACKEND_TEST"
echo ""

# ============================================================================
# 9. RESUMO E DIAGNÓSTICO
# ============================================================================
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    RESUMO E DIAGNÓSTICO${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Verificar se frontend está respondendo
FRONTEND_OK=$(echo "$FRONTEND_TEST" | grep -qE "200|301|302" && echo "OK" || echo "FAIL")
# Verificar se nginx consegue conectar ao frontend
NGINX_FRONTEND_OK=$(echo "$PROXY_TO_FRONTEND" | grep -qvE "ERRO_CONEXAO|timeout|Connection refused" && echo "OK" || echo "FAIL")

if [ "$FRONTEND_OK" = "FAIL" ]; then
    echo -e "${RED}[ERROR] PROBLEMA CRÍTICO: Frontend não está respondendo na porta 3000${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Soluções:${NC}"
    echo "   1. Reiniciar frontend:"
    echo "      docker restart ai_saas_frontend_prod"
    echo ""
    echo "   2. Verificar logs:"
    echo "      docker logs ai_saas_frontend_prod --tail 50"
    echo ""
elif [ "$NGINX_FRONTEND_OK" = "FAIL" ]; then
    echo -e "${RED}[ERROR] PROBLEMA CRÍTICO: Nginx não consegue conectar ao frontend${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Soluções:${NC}"
    echo "   1. Verificar se frontend está na mesma rede:"
    echo "      docker network inspect ai_saas_network"
    echo ""
    echo "   2. Reiniciar ambos:"
    echo "      docker restart ai_saas_frontend_prod ai_saas_proxy"
    echo ""
else
    echo -e "${GREEN}[OK] Conectividade básica OK${NC}"
    echo ""
fi

echo -e "${BLUE} Próximos passos:${NC}"
echo "   1. Se frontend não está respondendo, verifique os logs acima"
echo "   2. Se nginx não consegue conectar, verifique a rede Docker"
echo "   3. Se tudo parece OK mas ainda há 502, pode ser problema de timing"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

