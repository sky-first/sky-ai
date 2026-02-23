#!/bin/bash
# Script para verificar status dos containers na VM Azure
# Verifica se os containers estão rodando e funcionando corretamente

set -e

# Configurações
RESOURCE_GROUP="${1:-poc-sky}"
VM_NAME="${2:-poc-sky}"
VM_IP="${3:-20.86.142.1}"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    Verificando Status dos Containers${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}Resource Group:${NC} $RESOURCE_GROUP"
echo -e "${BLUE}VM Name:${NC} $VM_NAME"
echo -e "${BLUE}VM IP:${NC} $VM_IP"
echo ""

# Verificar Azure CLI
if ! command -v az >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Azure CLI não encontrado${NC}"
    echo "   Instale: https://docs.microsoft.com/cli/azure/install-azure-cli"
    exit 1
fi

# Verificar login
if ! az account show >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Não está logado no Azure CLI${NC}"
    echo "   Execute: az login"
    exit 1
fi

# Função para executar comando na VM
run_vm_command() {
    local scripts=("$@")
    az vm run-command invoke \
        --resource-group "$RESOURCE_GROUP" \
        --name "$VM_NAME" \
        --command-id RunShellScript \
        --scripts "${scripts[@]}" \
        --output json 2>&1 | jq -r '.value[0].message' 2>/dev/null || echo ""
}

echo -e "${BLUE}1. Verificando se Docker está rodando...${NC}"
DOCKER_STATUS=$(run_vm_command 'docker --version 2>&1 || echo "DOCKER_NAO_INSTALADO"')
if echo "$DOCKER_STATUS" | grep -q "DOCKER_NAO_INSTALADO"; then
    echo -e "${RED}[ERROR] Docker não está instalado na VM${NC}"
    exit 1
else
    echo -e "${GREEN}[OK] Docker está instalado${NC}"
    echo "$DOCKER_STATUS" | grep -i "version" | head -1 || true
fi
echo ""

echo -e "${BLUE}2. Verificando containers rodando...${NC}"
CONTAINERS_PS=$(run_vm_command \
    'cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || echo "DIR_NAO_ENCONTRADO"' \
    'if [ "$(pwd)" != "DIR_NAO_ENCONTRADO" ]; then sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1; else echo "ERRO_DIR"; fi')
    
if echo "$CONTAINERS_PS" | grep -q "ERRO_DIR"; then
    echo -e "${YELLOW}[WARNING] Diretório do projeto não encontrado, tentando docker ps direto...${NC}"
    CONTAINERS_PS=$(run_vm_command 'sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>&1')
fi

if [ -z "$CONTAINERS_PS" ] || echo "$CONTAINERS_PS" | grep -qE "(Cannot connect|permission denied)"; then
    echo -e "${RED}[ERROR] Erro ao verificar containers${NC}"
    echo "$CONTAINERS_PS"
else
    echo "$CONTAINERS_PS" | grep -v "^$" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | head -20
fi
echo ""

echo -e "${BLUE}3. Verificando docker compose status...${NC}"
COMPOSE_STATUS=$(run_vm_command \
    'cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || echo "DIR_NAO_ENCONTRADO"' \
    'if [ "$(pwd)" != "DIR_NAO_ENCONTRADO" ]; then sudo docker compose ps 2>&1 || sudo docker-compose ps 2>&1; else echo "ERRO_DIR"; fi')

if echo "$COMPOSE_STATUS" | grep -q "ERRO_DIR"; then
    echo -e "${YELLOW}[WARNING] Diretório do projeto não encontrado${NC}"
else
    echo "$COMPOSE_STATUS" | grep -v "^$" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | head -30
    
    # Verificar containers com problemas
    if echo "$COMPOSE_STATUS" | grep -qE "(Exit|Dead|unhealthy|restarting)"; then
        echo ""
        echo -e "${RED}[WARNING] ATENÇÃO: Alguns containers estão com problemas!${NC}"
        echo "$COMPOSE_STATUS" | grep -E "(Exit|Dead|unhealthy|restarting)" || true
    fi
fi
echo ""

echo -e "${BLUE}4. Verificando containers parados ou com erro...${NC}"
STOPPED_CONTAINERS=$(run_vm_command \
    'sudo docker ps -a --format "{{.Names}}: {{.Status}}" --filter "status=exited" --filter "status=dead" 2>&1 | head -20')

if [ -n "$STOPPED_CONTAINERS" ] && ! echo "$STOPPED_CONTAINERS" | grep -qE "(Cannot connect|permission denied|^$)"; then
    STOPPED_COUNT=$(echo "$STOPPED_CONTAINERS" | grep -v "^$" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | wc -l | tr -d ' ')
    if [ "$STOPPED_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}[WARNING] Containers parados encontrados:${NC}"
        echo "$STOPPED_CONTAINERS" | grep -v "^$" | grep -v "\[stdout\]" | grep -v "\[stderr\]"
        echo ""
        echo -e "${BLUE}[INFO] Verificando logs dos containers parados...${NC}"
        
        # Obter nomes dos containers parados
        CONTAINER_NAMES=$(echo "$STOPPED_CONTAINERS" | grep -v "^$" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | cut -d: -f1 | head -5)
        for container in $CONTAINER_NAMES; do
            if [ -n "$container" ]; then
                echo ""
                echo -e "${YELLOW} Logs de $container (últimas 20 linhas):${NC}"
                LOGS=$(run_vm_command "sudo docker logs $container --tail=20 2>&1")
                echo "$LOGS" | grep -v "^$" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | tail -20
            fi
        done
    else
        echo -e "${GREEN}[OK] Nenhum container parado encontrado${NC}"
    fi
else
    echo -e "${GREEN}[OK] Nenhum container parado encontrado${NC}"
fi
echo ""

echo -e "${BLUE}5. Verificando containers críticos...${NC}"
CRITICAL_CONTAINERS=("ai_saas_postgres_prod" "ai_saas_redis_prod" "ai_saas_backend_prod" "ai_saas_proxy" "ai_saas_frontend_prod")
MISSING_CONTAINERS=""
FAILED_CONTAINERS=""

for container in "${CRITICAL_CONTAINERS[@]}"; do
    CONTAINER_CHECK=$(run_vm_command "sudo docker ps --format '{{.Names}}' | grep -q '^${container}$' && echo 'RUNNING' || echo 'NOT_RUNNING'")
    
    if echo "$CONTAINER_CHECK" | grep -q "RUNNING"; then
        echo -e "${GREEN}[OK] $container está rodando${NC}"
    else
        echo -e "${RED}[ERROR] $container NÃO está rodando${NC}"
        MISSING_CONTAINERS="${MISSING_CONTAINERS} ${container}"
        
        # Verificar se está parado com erro
        EXIT_CODE=$(run_vm_command "sudo docker inspect $container --format='{{.State.ExitCode}}' 2>&1" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | grep -v "^$" | head -1)
        if [ -n "$EXIT_CODE" ] && [ "$EXIT_CODE" != "0" ] && [ "$EXIT_CODE" != "null" ]; then
            FAILED_CONTAINERS="${FAILED_CONTAINERS} ${container}(exit:$EXIT_CODE)"
            echo -e "${YELLOW}   Exit code: $EXIT_CODE${NC}"
            
            # Mostrar últimas linhas do log
            echo -e "${YELLOW}   Últimas linhas do log:${NC}"
            LOGS=$(run_vm_command "sudo docker logs $container --tail=10 2>&1")
            echo "$LOGS" | grep -v "^$" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | tail -5 | sed 's/^/      /'
        fi
    fi
done
echo ""

echo -e "${BLUE}6. Verificando saúde dos serviços...${NC}"

# PostgreSQL
echo -n "PostgreSQL: "
PG_CHECK=$(run_vm_command "sudo docker exec ai_saas_postgres_prod pg_isready -U postgres 2>&1" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | grep -v "^$")
if echo "$PG_CHECK" | grep -q "accepting connections"; then
    echo -e "${GREEN}[OK] OK${NC}"
else
    echo -e "${RED}[ERROR] Não está respondendo${NC}"
fi

# Redis
echo -n "Redis: "
REDIS_CHECK=$(run_vm_command "sudo docker exec ai_saas_redis_prod redis-cli ping 2>&1" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | grep -v "^$")
if echo "$REDIS_CHECK" | grep -qE "PONG|NOAUTH"; then
    echo -e "${GREEN}[OK] OK${NC}"
else
    echo -e "${RED}[ERROR] Não está respondendo${NC}"
fi

# Backend
echo -n "Backend (porta 8000): "
BACKEND_CHECK=$(run_vm_command "curl -f -s http://localhost:8000/health > /dev/null 2>&1 || curl -f -s http://localhost:8000/api/v1/health > /dev/null 2>&1 && echo 'OK' || echo 'FAIL'" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | grep -v "^$")
if echo "$BACKEND_CHECK" | grep -q "OK"; then
    echo -e "${GREEN}[OK] OK${NC}"
else
    echo -e "${RED}[ERROR] Não está respondendo${NC}"
fi

# Proxy/Nginx
echo -n "Proxy/Nginx (porta 80): "
PROXY_CHECK=$(run_vm_command "curl -f -s http://localhost > /dev/null 2>&1 && echo 'OK' || echo 'FAIL'" | grep -v "\[stdout\]" | grep -v "\[stderr\]" | grep -v "^$")
if echo "$PROXY_CHECK" | grep -q "OK"; then
    echo -e "${GREEN}[OK] OK${NC}"
else
    echo -e "${RED}[ERROR] Não está respondendo${NC}"
fi
echo ""

echo -e "${BLUE}7. Verificando recursos do sistema...${NC}"
SYSTEM_INFO=$(run_vm_command \
    'echo "CPU: $(top -bn1 | grep "Cpu(s)" | awk '\''{print $2}'\'' | cut -d% -f1)%"' \
    'echo "Memória: $(free | grep Mem | awk '\''{printf "%.0f", $3/$2 * 100}'\'')%"' \
    'echo "Disco: $(df -h / | awk '\''NR==2 {print $5}'\'')"')

echo "$SYSTEM_INFO" | grep -v "^$" | grep -v "\[stdout\]" | grep -v "\[stderr\]"
echo ""

# Resumo final
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    Resumo${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

if [ -n "$MISSING_CONTAINERS" ]; then
    echo -e "${RED}[ERROR] Containers faltando:${NC}$MISSING_CONTAINERS"
    echo ""
    echo -e "${YELLOW}[INFO] Para reiniciar os containers:${NC}"
    echo "   az vm run-command invoke \\"
    echo "     -g $RESOURCE_GROUP \\"
    echo "     -n $VM_NAME \\"
    echo "     --command-id RunShellScript \\"
    echo "     --scripts 'cd /home/azureuser/projeto/sky-poc-infra && sudo docker compose up -d'"
    echo ""
    exit 1
else
    echo -e "${GREEN}[OK] Todos os containers críticos estão rodando${NC}"
    echo ""
    echo -e "${BLUE}[INFO] Para ver logs em tempo real:${NC}"
    echo "   az vm run-command invoke \\"
    echo "     -g $RESOURCE_GROUP \\"
    echo "     -n $VM_NAME \\"
    echo "     --command-id RunShellScript \\"
    echo "     --scripts 'cd /home/azureuser/projeto/sky-poc-infra && sudo docker compose logs -f'"
    echo ""
    exit 0
fi

