#!/bin/bash
# Script para iniciar todos os containers

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
echo -e "${CYAN}    Iniciando Todos os Containers${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Função para executar comando
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

echo -e "${BLUE}1. Verificando containers parados...${NC}"
STOPPED=$(run_vm_command 'docker ps -a --format "{{.Names}}: {{.Status}}" | grep -E "(Exited|Dead|Created)"')
if [ -n "$STOPPED" ]; then
    echo "$STOPPED"
else
    echo "Nenhum container parado encontrado"
fi
echo ""

echo -e "${BLUE}2. Localizando diretório do projeto...${NC}"
PROJECT_DIR=$(run_vm_command 'if [ -d "/home/azureuser/projeto/sky-poc-infra" ]; then echo "/home/azureuser/projeto/sky-poc-infra"; elif [ -d "/home/azureuser/projeto/poc-deploy" ]; then echo "/home/azureuser/projeto/poc-deploy"; else echo "NAO_ENCONTRADO"; fi')
echo "Diretório: $PROJECT_DIR"
echo ""

if echo "$PROJECT_DIR" | grep -q "NAO_ENCONTRADO"; then
    echo -e "${RED}[ERROR] Diretório do projeto não encontrado!${NC}"
    exit 1
fi

echo -e "${YELLOW}3. Iniciando todos os containers com docker compose...${NC}"
START_RESULT=$(run_vm_command "cd $PROJECT_DIR && docker compose up -d 2>&1")
echo "$START_RESULT"
echo ""

echo -e "${BLUE}4. Aguardando 15 segundos para containers iniciarem...${NC}"
sleep 15
echo ""

echo -e "${BLUE}5. Verificando status dos containers...${NC}"
STATUS=$(run_vm_command 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
echo "$STATUS"
echo ""

echo -e "${BLUE}6. Verificando containers críticos...${NC}"
echo ""

CRITICAL_CONTAINERS=("ai_saas_postgres_prod" "ai_saas_redis_prod" "ai_saas_backend_prod" "ai_saas_frontend_prod" "ai_saas_proxy")

ALL_OK=true
for container in "${CRITICAL_CONTAINERS[@]}"; do
    CONTAINER_STATUS=$(run_vm_command "docker ps --filter 'name=$container' --format '{{.Status}}'")
    if [ -n "$CONTAINER_STATUS" ]; then
        echo -e "  ${GREEN}[OK] $container: $CONTAINER_STATUS${NC}"
    else
        echo -e "  ${RED}[ERROR] $container: NÃO ESTÁ RODANDO${NC}"
        ALL_OK=false
    fi
done

echo ""
echo -e "${BLUE}7. Verificando porta 80 (nginx)...${NC}"
PORT_80=$(run_vm_command 'docker ps --filter "name=ai_saas_proxy" --format "{{.Ports}}" | grep "0.0.0.0:80"')
if [ -n "$PORT_80" ]; then
    echo -e "${GREEN}[OK] Porta 80 está mapeada: $PORT_80${NC}"
else
    echo -e "${RED}[ERROR] Porta 80 NÃO está mapeada!${NC}"
    ALL_OK=false
fi
echo ""

echo -e "${BLUE}8. Testando nginx localmente...${NC}"
NGINX_TEST=$(run_vm_command 'curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost 2>&1 || echo "ERRO"')
if echo "$NGINX_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}[OK] Nginx está respondendo: $NGINX_TEST${NC}"
else
    echo -e "${YELLOW}[WARNING] Nginx ainda não está respondendo: $NGINX_TEST${NC}"
    echo -e "${YELLOW}   (Pode estar ainda iniciando - aguarde mais alguns segundos)${NC}"
fi
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   📊 RESUMO${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

if [ "$ALL_OK" = true ] && [ -n "$PORT_80" ]; then
    echo -e "${GREEN}[OK] Todos os containers críticos estão rodando!${NC}"
    echo ""
    echo -e "${BLUE}[INFO] Teste acessando: http://20.185.60.67${NC}"
    echo ""
    echo -e "${YELLOW}[WARNING] Se ainda houver ERR_CONNECTION_REFUSED:${NC}"
    echo "   1. Verifique NSG no Azure Portal (portas 80 e 443)"
    echo "   2. Aguarde mais 1-2 minutos (containers podem estar ainda iniciando)"
    echo "   3. Verifique logs: docker logs ai_saas_proxy"
else
    echo -e "${RED}[ERROR] Alguns containers não estão rodando${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Tente novamente:${NC}"
    echo "   cd $PROJECT_DIR && docker compose up -d"
    echo ""
    echo -e "${YELLOW}[INFO] Ou verifique logs:${NC}"
    echo "   docker compose logs"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

