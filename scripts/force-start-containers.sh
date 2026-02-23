#!/bin/bash
# Script que aguarda comando anterior e força início dos containers

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
echo -e "${CYAN}    Aguardando e Iniciando Containers${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Função para tentar executar com retry
try_execute_with_retry() {
    local max_attempts=30  # 5 minutos (30 * 10s)
    local wait_interval=10
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        echo -e "${BLUE} Tentativa $attempt/$max_attempts...${NC}"
        
        local result=$(az vm run-command invoke \
            --resource-group "$RESOURCE_GROUP" \
            --name "$VM_NAME" \
            --command-id RunShellScript \
            --scripts "$@" \
            --output json 2>&1)
        
        if echo "$result" | grep -q "Conflict"; then
            if [ $attempt -lt $max_attempts ]; then
                echo -e "${YELLOW} Comando anterior ainda em execução. Aguardando ${wait_interval}s...${NC}"
                sleep $wait_interval
                attempt=$((attempt + 1))
            else
                echo -e "${RED}[ERROR] Timeout após ${max_attempts} tentativas${NC}"
                echo -e "${YELLOW}[INFO] O comando anterior pode estar travado${NC}"
                echo -e "${YELLOW}[INFO] Tente reiniciar a extensão de run-command na VM ou aguarde mais tempo${NC}"
                return 1
            fi
        else
            # Sucesso
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

echo -e "${BLUE}1. Verificando status atual dos containers...${NC}"
try_execute_with_retry 'docker ps -a --format "{{.Names}}: {{.Status}}" | head -10'
echo ""

echo -e "${YELLOW}2. Iniciando todos os containers...${NC}"
START_RESULT=$(try_execute_with_retry 'docker start ai_saas_postgres_prod ai_saas_redis_prod ai_saas_backend_prod ai_saas_frontend_prod ai_saas_proxy 2>&1 || echo "ERRO_AO_INICIAR"')
echo "$START_RESULT"
echo ""

if echo "$START_RESULT" | grep -q "ERRO_AO_INICIAR"; then
    echo -e "${RED}[ERROR] Erro ao iniciar containers${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Tentando iniciar um por vez...${NC}"
    
    for container in ai_saas_postgres_prod ai_saas_redis_prod ai_saas_backend_prod ai_saas_frontend_prod ai_saas_proxy; do
        echo -n "  Iniciando $container... "
        CONTAINER_START=$(try_execute_with_retry "docker start $container 2>&1")
        if echo "$CONTAINER_START" | grep -q "$container"; then
            echo -e "${GREEN}[OK]${NC}"
        else
            echo -e "${RED}[ERROR]${NC}"
        fi
    done
    echo ""
fi

echo -e "${BLUE}3. Aguardando 20 segundos para containers iniciarem...${NC}"
sleep 20
echo ""

echo -e "${BLUE}4. Verificando status final...${NC}"
FINAL_STATUS=$(try_execute_with_retry 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
echo "$FINAL_STATUS"
echo ""

echo -e "${BLUE}5. Verificando containers críticos...${NC}"
echo ""

CRITICAL_CONTAINERS=("ai_saas_postgres_prod" "ai_saas_redis_prod" "ai_saas_backend_prod" "ai_saas_frontend_prod" "ai_saas_proxy")
ALL_OK=true

for container in "${CRITICAL_CONTAINERS[@]}"; do
    CONTAINER_STATUS=$(try_execute_with_retry "docker ps --filter 'name=$container' --format '{{.Status}}'")
    if [ -n "$CONTAINER_STATUS" ]; then
        echo -e "  ${GREEN}[OK] $container: $CONTAINER_STATUS${NC}"
    else
        echo -e "  ${RED}[ERROR] $container: NÃO ESTÁ RODANDO${NC}"
        ALL_OK=false
    fi
done

echo ""
echo -e "${BLUE}6. Verificando porta 80 (nginx)...${NC}"
PORT_80=$(try_execute_with_retry 'docker ps --filter "name=ai_saas_proxy" --format "{{.Ports}}" | grep "0.0.0.0:80"')
if [ -n "$PORT_80" ]; then
    echo -e "${GREEN}[OK] Porta 80 está mapeada${NC}"
else
    echo -e "${RED}[ERROR] Porta 80 NÃO está mapeada${NC}"
    ALL_OK=false
fi
echo ""

echo -e "${BLUE}7. Testando nginx localmente...${NC}"
NGINX_TEST=$(try_execute_with_retry 'curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost 2>&1 || echo "ERRO"')
if echo "$NGINX_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}[OK] Nginx está respondendo: $NGINX_TEST${NC}"
else
    echo -e "${YELLOW}[WARNING] Nginx ainda não está respondendo: $NGINX_TEST${NC}"
    echo -e "${YELLOW}   (Pode estar ainda iniciando)${NC}"
fi
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    RESUMO${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

if [ "$ALL_OK" = true ] && [ -n "$PORT_80" ]; then
    echo -e "${GREEN}[OK] Todos os containers estão rodando!${NC}"
    echo ""
    echo -e "${BLUE}[INFO] Teste acessando: http://20.185.60.67${NC}"
    echo ""
    if echo "$NGINX_TEST" | grep -qE "200|301|302|404"; then
        echo -e "${GREEN}[OK] Nginx está respondendo - o site deve estar acessível!${NC}"
    else
        echo -e "${YELLOW}[WARNING] Aguarde mais 1-2 minutos para o nginx terminar de iniciar${NC}"
    fi
else
    echo -e "${RED}[ERROR] Alguns containers não estão rodando${NC}"
    echo ""
    echo -e "${YELLOW}[INFO] Verifique os logs:${NC}"
    echo "   docker logs ai_saas_proxy"
    echo "   docker logs ai_saas_frontend_prod"
    echo ""
    echo -e "${YELLOW}[INFO] Ou tente reiniciar manualmente:${NC}"
    echo "   docker restart ai_saas_proxy"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

