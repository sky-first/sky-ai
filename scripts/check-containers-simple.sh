#!/bin/bash
# Script simplificado para verificar status dos containers
# Verifica conectividade HTTP direta (não requer Azure CLI)

set -e

VM_IP="${1:-20.86.142.1}"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    Verificando Status dos Containers (HTTP)${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}VM IP:${NC} $VM_IP"
echo ""

FAILED=0

# Função para testar endpoint
test_endpoint() {
    local name=$1
    local url=$2
    local timeout=${3:-5}
    
    echo -n "Testando $name... "
    if curl -f -s --connect-timeout $timeout "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}[OK] OK${NC}"
        return 0
    else
        echo -e "${RED}[ERROR] FALHOU${NC}"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

echo -e "${BLUE}1. Testando conectividade básica...${NC}"
if ping -c 1 -W 2 "$VM_IP" > /dev/null 2>&1; then
    echo -e "${GREEN}[OK] VM está acessível (ping)${NC}"
else
    echo -e "${YELLOW}[WARNING] Ping falhou (pode estar bloqueado, mas HTTP pode funcionar)${NC}"
fi
echo ""

echo -e "${BLUE}2. Testando endpoints HTTP...${NC}"
echo ""

# Frontend (porta 80)
test_endpoint "Frontend (http://$VM_IP)" "http://$VM_IP"

# Frontend login
test_endpoint "Frontend Login (http://$VM_IP/login)" "http://$VM_IP/login"

# API Health
test_endpoint "API Health (http://$VM_IP/api/v1/health)" "http://$VM_IP/api/v1/health"

# API Root
test_endpoint "API Root (http://$VM_IP/api/v1)" "http://$VM_IP/api/v1"

echo ""

echo -e "${BLUE}3. Verificando resposta HTTP detalhada...${NC}"
echo ""

# Obter headers do frontend
echo "Headers do Frontend:"
HTTP_HEADERS=$(curl -I -s --connect-timeout 5 "http://$VM_IP" 2>&1 || echo "ERRO")
if echo "$HTTP_HEADERS" | grep -q "HTTP/"; then
    echo "$HTTP_HEADERS" | head -10 | grep -E "(HTTP/|Server:|Content-Type:)" || true
else
    echo -e "${RED}[ERROR] Não foi possível obter headers${NC}"
    echo "$HTTP_HEADERS"
fi
echo ""

# Obter status code
echo "Status Code:"
STATUS_CODE=$(curl -o /dev/null -s -w "%{http_code}" --connect-timeout 5 "http://$VM_IP" 2>&1 || echo "000")
if [ "$STATUS_CODE" = "200" ] || [ "$STATUS_CODE" = "301" ] || [ "$STATUS_CODE" = "302" ]; then
    echo -e "${GREEN}[OK] HTTP $STATUS_CODE${NC}"
elif [ "$STATUS_CODE" = "000" ]; then
    echo -e "${RED}[ERROR] Timeout ou conexão recusada${NC}"
    FAILED=$((FAILED + 1))
else
    echo -e "${YELLOW}[WARNING] HTTP $STATUS_CODE${NC}"
    FAILED=$((FAILED + 1))
fi
echo ""

echo -e "${BLUE}4. Diagnóstico...${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}[OK] Todos os endpoints estão respondendo${NC}"
    echo ""
    echo -e "${BLUE}[INFO] A aplicação parece estar funcionando!${NC}"
    echo "   Acesse: http://$VM_IP"
    echo ""
    exit 0
else
    echo -e "${RED}[ERROR] Alguns endpoints não estão respondendo${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Possíveis causas:${NC}"
    echo "   1. Containers não estão rodando"
    echo "   2. Nginx/Proxy não está funcionando"
    echo "   3. Firewall/NSG bloqueando conexões"
    echo "   4. VM pode estar reiniciando"
    echo ""
    echo -e "${BLUE}[INFO] Para verificar containers na VM:${NC}"
    echo "   bash scripts/check-containers-status.sh poc-sky poc-sky $VM_IP"
    echo ""
    echo -e "${BLUE}[INFO] Ou via Azure Portal:${NC}"
    echo "   1. Acesse: https://portal.azure.com"
    echo "   2. Vá em: Virtual Machines > poc-sky"
    echo "   3. Clique em 'Run command' > 'RunShellScript'"
    echo "   4. Execute: sudo docker ps"
    echo ""
    exit 1
fi

