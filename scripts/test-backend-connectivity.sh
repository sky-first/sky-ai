#!/bin/bash
# Script para testar conectividade do backend com todos os serviços

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
echo -e "${CYAN}   🔗 Teste de Conectividade do Backend${NC}"
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

echo -e "${BLUE}Executando testes de conectividade dentro do container backend...${NC}"
echo ""

# Teste 1: PostgreSQL
echo -e "${BLUE}1️⃣ Testando PostgreSQL (postgres:5432)...${NC}"
PG_TEST=$(run_vm_command 'docker exec ai_saas_backend_prod python3 -c "import socket; s = socket.socket(); s.settimeout(3); result = s.connect_ex((\"postgres\", 5432)); s.close(); print(\"OK\" if result == 0 else \"FAIL\")" 2>&1')
if echo "$PG_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ PostgreSQL: Conectividade OK${NC}"
else
    echo -e "${RED}❌ PostgreSQL: Falha na conexão${NC}"
    echo "$PG_TEST"
fi
echo ""

# Teste 2: Redis
echo -e "${BLUE}2️⃣ Testando Redis (redis:6379)...${NC}"
REDIS_TEST=$(run_vm_command 'docker exec ai_saas_backend_prod python3 -c "import socket; s = socket.socket(); s.settimeout(3); result = s.connect_ex((\"redis\", 6379)); s.close(); print(\"OK\" if result == 0 else \"FAIL\")" 2>&1')
if echo "$REDIS_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ Redis: Conectividade OK${NC}"
else
    echo -e "${RED}❌ Redis: Falha na conexão${NC}"
    echo "$REDIS_TEST"
fi
echo ""

# Teste 3: Frontend
echo -e "${BLUE}3️⃣ Testando Frontend (frontend:3000)...${NC}"
FRONTEND_TEST=$(run_vm_command 'docker exec ai_saas_backend_prod python3 -c "import socket; s = socket.socket(); s.settimeout(3); result = s.connect_ex((\"frontend\", 3000)); s.close(); print(\"OK\" if result == 0 else \"FAIL\")" 2>&1')
if echo "$FRONTEND_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ Frontend: Conectividade OK${NC}"
else
    echo -e "${RED}❌ Frontend: Falha na conexão${NC}"
    echo "$FRONTEND_TEST"
fi
echo ""

# Teste 4: Nginx/Proxy
echo -e "${BLUE}4️⃣ Testando Nginx/Proxy (proxy:80)...${NC}"
PROXY_TEST=$(run_vm_command 'docker exec ai_saas_backend_prod python3 -c "import socket; s = socket.socket(); s.settimeout(3); result = s.connect_ex((\"proxy\", 80)); s.close(); print(\"OK\" if result == 0 else \"FAIL\")" 2>&1')
if echo "$PROXY_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ Nginx: Conectividade OK${NC}"
else
    echo -e "${RED}❌ Nginx: Falha na conexão${NC}"
    echo "$PROXY_TEST"
fi
echo ""

# Teste 5: AI Service
echo -e "${BLUE}5️⃣ Testando AI Service (ai:8001)...${NC}"
AI_TEST=$(run_vm_command 'docker exec ai_saas_backend_prod python3 -c "import socket; s = socket.socket(); s.settimeout(3); result = s.connect_ex((\"ai\", 8001)); s.close(); print(\"OK\" if result == 0 else \"FAIL\")" 2>&1')
if echo "$AI_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ AI Service: Conectividade OK${NC}"
else
    echo -e "${YELLOW}⚠️  AI Service: Falha na conexão (pode ser normal se não estiver rodando)${NC}"
    echo "$AI_TEST"
fi
echo ""

# Teste 6: HTTP endpoints
echo -e "${BLUE}6️⃣ Testando HTTP endpoints...${NC}"
echo ""

echo -n "  Frontend HTTP (http://frontend:3000): "
FRONTEND_HTTP=$(run_vm_command 'docker exec ai_saas_backend_prod python3 -c "import urllib.request; r = urllib.request.urlopen(\"http://frontend:3000\", timeout=5); print(r.getcode())" 2>&1')
if echo "$FRONTEND_HTTP" | grep -qE "200|301|302"; then
    echo -e "${GREEN}✅ HTTP $FRONTEND_HTTP${NC}"
else
    echo -e "${RED}❌ $FRONTEND_HTTP${NC}"
fi

echo -n "  Backend HTTP (http://localhost:8000/health): "
BACKEND_HTTP=$(run_vm_command 'docker exec ai_saas_backend_prod python3 -c "import urllib.request; r = urllib.request.urlopen(\"http://localhost:8000/health\", timeout=5); print(r.getcode())" 2>&1')
if echo "$BACKEND_HTTP" | grep -qE "200|301|302"; then
    echo -e "${GREEN}✅ HTTP $BACKEND_HTTP${NC}"
else
    echo -e "${RED}❌ $BACKEND_HTTP${NC}"
fi

echo -n "  Nginx HTTP (http://proxy:80): "
PROXY_HTTP=$(run_vm_command 'docker exec ai_saas_backend_prod python3 -c "import urllib.request; r = urllib.request.urlopen(\"http://proxy:80\", timeout=5); print(r.getcode())" 2>&1')
if echo "$PROXY_HTTP" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}✅ HTTP $PROXY_HTTP${NC}"
else
    echo -e "${RED}❌ $PROXY_HTTP${NC}"
fi
echo ""

# Teste 7: Resolução DNS
echo -e "${BLUE}7️⃣ Verificando resolução DNS...${NC}"
DNS_TEST=$(run_vm_command 'docker exec ai_saas_backend_prod python3 -c "import socket; services = [\"postgres\", \"redis\", \"frontend\", \"backend\", \"proxy\", \"ai\"]; [print(f\"{s}: {socket.gethostbyname(s)}\") for s in services]" 2>&1')
echo "$DNS_TEST"
echo ""

# Teste 8: Variáveis de ambiente
echo -e "${BLUE}8️⃣ Verificando variáveis de ambiente...${NC}"
ENV_TEST=$(run_vm_command 'docker exec ai_saas_backend_prod sh -c "echo DATABASE_URL: \$DATABASE_URL | head -c 80 && echo \"...\" && echo REDIS_URL: \$REDIS_URL | head -c 60 && echo \"...\"" 2>&1')
echo "$ENV_TEST"
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   📊 Resumo${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Contar sucessos
SUCCESS_COUNT=0
TOTAL_TESTS=5

if echo "$PG_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ PostgreSQL: OK${NC}"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
else
    echo -e "${RED}❌ PostgreSQL: FALHOU${NC}"
fi

if echo "$REDIS_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ Redis: OK${NC}"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
else
    echo -e "${RED}❌ Redis: FALHOU${NC}"
fi

if echo "$FRONTEND_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ Frontend: OK${NC}"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
else
    echo -e "${RED}❌ Frontend: FALHOU${NC}"
fi

if echo "$PROXY_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ Nginx: OK${NC}"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
else
    echo -e "${RED}❌ Nginx: FALHOU${NC}"
fi

if echo "$AI_TEST" | grep -q "OK"; then
    echo -e "${GREEN}✅ AI Service: OK${NC}"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
else
    echo -e "${YELLOW}⚠️  AI Service: Não disponível (pode ser normal)${NC}"
fi

echo ""
echo -e "${BLUE}Resultado: $SUCCESS_COUNT/$TOTAL_TESTS serviços acessíveis${NC}"

if [ $SUCCESS_COUNT -eq $TOTAL_TESTS ]; then
    echo -e "${GREEN}✅ Todos os serviços críticos estão acessíveis!${NC}"
elif [ $SUCCESS_COUNT -ge 3 ]; then
    echo -e "${YELLOW}⚠️  Alguns serviços não estão acessíveis${NC}"
else
    echo -e "${RED}❌ Muitos serviços não estão acessíveis - verifique a rede Docker${NC}"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
