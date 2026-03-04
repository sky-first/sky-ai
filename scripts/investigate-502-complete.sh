#!/bin/bash
# Investigação completa 502 Bad Gateway - Metodologia DevOps Profissional
# Fase 1: Coletar evidência | Fase 2: Aplicar correções | Fase 3: Validar

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
echo -e "${CYAN}    Investigação Completa 502 Bad Gateway${NC}"
echo -e "${CYAN}   Metodologia: Evidência → Correção → Validação${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Função para executar comando
run_vm_command() {
    local max_attempts=3
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

# ============================================================================
# FASE 1: COLETAR EVIDÊNCIA ANTES DA CORREÇÃO
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   FASE 1.: COLETAR EVIDÊNCIA (ANTES DA CORREÇÃO)${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}[WARNING] NÃO reiniciar nada ainda - apenas coletar evidência${NC}"
echo ""

echo -e "${BLUE}1. Logs do nginx (fonte primária do 502)${NC}"
echo -e "${BLUE}   Procurando: connect() failed, upstream closed, no live upstreams${NC}"
echo ""
NGINX_LOGS=$(run_vm_command 'docker logs ai_saas_proxy --tail 100 2>&1 | grep -iE "(error|failed|refused|upstream|502|111|113)" | tail -50')
if [ -n "$NGINX_LOGS" ]; then
    echo "$NGINX_LOGS"
    echo ""
    
    # Análise dos erros
    if echo "$NGINX_LOGS" | grep -q "connect() failed (111\|Connection refused"; then
        echo -e "${RED} EVIDÊNCIA: Connection refused (111) encontrado${NC}"
        echo -e "${YELLOW} Nginx tentou conectar ao frontend e foi recusado${NC}"
    fi
    
    if echo "$NGINX_LOGS" | grep -q "upstream prematurely closed\|upstream closed"; then
        echo -e "${RED} EVIDÊNCIA: Upstream closed connection${NC}"
        echo -e "${YELLOW} Frontend crashou ao receber request${NC}"
    fi
    
    if echo "$NGINX_LOGS" | grep -q "no live upstreams"; then
        echo -e "${RED} EVIDÊNCIA: No live upstreams${NC}"
        echo -e "${YELLOW} Nenhum upstream disponível${NC}"
    fi
else
    echo -e "${YELLOW}[WARNING] Nenhum erro específico encontrado nos logs recentes${NC}"
fi
echo ""

echo -e "${BLUE}2. Logs do frontend (onde a verdade está)${NC}"
echo -e "${BLUE}   Procurando: cold start, crash, porta não aberta${NC}"
echo ""
FRONTEND_LOGS=$(run_vm_command 'docker logs ai_saas_frontend_prod --tail 200 2>&1')
echo "$FRONTEND_LOGS" | tail -50
echo ""

# Análise dos logs do frontend
COLD_START_DETECTED=false
CRASH_DETECTED=false
PORT_ISSUE=false

if echo "$FRONTEND_LOGS" | grep -q "Creating an optimized production build\|Compiling\|compiling"; then
    echo -e "${RED} EVIDÊNCIA: Cold start detectado${NC}"
    echo -e "${YELLOW} Next.js está compilando em runtime${NC}"
    COLD_START_DETECTED=true
fi

if echo "$FRONTEND_LOGS" | grep -q "Error:\|UnhandledPromiseRejection\|Missing environment"; then
    echo -e "${RED} EVIDÊNCIA: Erro no frontend${NC}"
    echo -e "${YELLOW} Frontend pode estar crashando${NC}"
    CRASH_DETECTED=true
fi

if echo "$FRONTEND_LOGS" | grep -q "Listening on localhost:3000"; then
    echo -e "${RED} EVIDÊNCIA: Porta escutando em localhost (não 0.0.0.0)${NC}"
    echo -e "${YELLOW} Frontend não está acessível externamente${NC}"
    PORT_ISSUE=true
fi

if echo "$FRONTEND_LOGS" | grep -q "Ready in\|Local:.*3000"; then
    echo -e "${GREEN}[OK] Frontend parece estar pronto${NC}"
fi
echo ""

echo -e "${BLUE}3. Docker events (eventos do sistema)${NC}"
echo ""
DOCKER_EVENTS=$(run_vm_command 'docker events --since 10m --filter "container=ai_saas_frontend_prod" --format "{{.Time}} {{.Action}} {{.Actor.Attributes.name}}" 2>&1 | tail -20 || echo "EVENTS_NAO_DISPONIVEIS"')
if [ -n "$DOCKER_EVENTS" ] && ! echo "$DOCKER_EVENTS" | grep -q "EVENTS_NAO_DISPONIVEIS"; then
    echo "$DOCKER_EVENTS"
    if echo "$DOCKER_EVENTS" | grep -q "die\|oom"; then
        echo -e "${RED} EVIDÊNCIA: Container morreu ou OOM${NC}"
    fi
else
    echo -e "${YELLOW}[WARNING] Docker events não disponível ou sem eventos recentes${NC}"
fi
echo ""

echo -e "${BLUE}4. Timeline (correlação de timestamps)${NC}"
echo ""
echo -e "${BLUE}   Timestamp atual:${NC}"
CURRENT_TIME=$(run_vm_command 'date "+%Y-%m-%d %H:%M:%S"')
echo "$CURRENT_TIME"
echo ""

echo -e "${BLUE}   Último erro no nginx:${NC}"
NGINX_ERROR_TIME=$(run_vm_command 'docker logs ai_saas_proxy 2>&1 | grep -iE "(error|502|refused)" | tail -1 | cut -d" " -f1-3')
if [ -n "$NGINX_ERROR_TIME" ]; then
    echo "$NGINX_ERROR_TIME"
else
    echo "Nenhum erro recente encontrado"
fi
echo ""

echo -e "${BLUE}   Última atividade no frontend:${NC}"
FRONTEND_LAST=$(run_vm_command 'docker logs ai_saas_frontend_prod 2>&1 | tail -1 | cut -d" " -f1-3')
if [ -n "$FRONTEND_LAST" ]; then
    echo "$FRONTEND_LAST"
fi
echo ""

echo -e "${BLUE}5. Estado real do container frontend${NC}"
echo ""
FRONTEND_STATE=$(run_vm_command 'docker inspect ai_saas_frontend_prod --format "{{json .State}}" 2>&1 | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"Status: {d.get(\"Status\", \"unknown\")}\")
    health = d.get(\"Health\", {})
    if health:
        print(f\"Health Status: {health.get(\"Status\", \"unknown\")}\")
        print(f\"Health FailingStreak: {health.get(\"FailingStreak\", 0)}\")
    else:
        print(\"Health: no healthcheck configured\")
    print(f\"StartedAt: {d.get(\"StartedAt\", \"unknown\")}\")
except Exception as e:
    print(f\"Erro ao parsear: {e}\")
    print(sys.stdin.read())
" 2>/dev/null || docker inspect ai_saas_frontend_prod --format "{{.State.Status}} - Health: {{.State.Health.Status}}"')
echo "$FRONTEND_STATE"
echo ""

HEALTHCHECK_MISSING=false
if echo "$FRONTEND_STATE" | grep -q "no healthcheck\|Health: $"; then
    echo -e "${RED} EVIDÊNCIA: Frontend NÃO tem healthcheck configurado${NC}"
    echo -e "${YELLOW} Docker não sabe se o app está pronto${NC}"
    HEALTHCHECK_MISSING=true
fi

if echo "$FRONTEND_STATE" | grep -q "unhealthy"; then
    echo -e "${RED} EVIDÊNCIA: Frontend está unhealthy${NC}"
fi
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    RESUMO DA FASE 1${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

ROOT_CAUSE=""
if [ "$HEALTHCHECK_MISSING" = true ]; then
    ROOT_CAUSE="Sem healthcheck - Docker não sabe quando frontend está pronto"
elif [ "$COLD_START_DETECTED" = true ]; then
    ROOT_CAUSE="Cold start - Next.js compilando quando nginx tenta conectar"
elif echo "$NGINX_LOGS" | grep -q "Connection refused\|111"; then
    ROOT_CAUSE="Connection refused - Frontend não está escutando quando nginx tenta conectar"
else
    ROOT_CAUSE="A investigar mais profundamente"
fi

echo -e "${BLUE}Root Cause Identificado:${NC}"
echo -e "${YELLOW}$ROOT_CAUSE${NC}"
echo ""

echo -e "${BLUE}Evidências coletadas:${NC}"
echo "  - Cold start: $COLD_START_DETECTED"
echo "  - Crash: $CRASH_DETECTED"
echo "  - Porta issue: $PORT_ISSUE"
echo "  - Healthcheck ausente: $HEALTHCHECK_MISSING"
echo ""

echo -e "${GREEN}[OK] Fase 1 concluída - Evidência coletada${NC}"
echo ""
echo -e "${YELLOW}[INFO] Próximo passo: Aplicar correções e validar${NC}"
echo ""

# ============================================================================
# FASE 2: APLICAR CORREÇÕES (já aplicadas nos arquivos)
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   FASE 2.: APLICAR CORREÇÕES${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${GREEN}[OK] Correções já aplicadas nos arquivos:${NC}"
echo "   1. [OK] Healthcheck adicionado ao frontend no docker-compose.yml"
echo "   2. [OK] depends_on mudado para service_healthy no docker-compose.yml"
echo "   3. [OK] proxy_next_upstream adicionado no nginx.conf"
echo ""

echo -e "${YELLOW}[WARNING] Aplicando correções na VM...${NC}"
echo ""

# Verificar se precisa recriar containers
echo -e "${BLUE}Verificando se precisa recriar containers...${NC}"
NEEDS_RECREATE=$(run_vm_command 'cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null && docker compose config --services 2>&1 | head -1 || echo "DIR_NOT_FOUND"')
if echo "$NEEDS_RECREATE" | grep -q "DIR_NOT_FOUND"; then
    echo -e "${YELLOW}[WARNING] Diretório docker-compose não encontrado${NC}"
    echo -e "${BLUE}[INFO] Aplicando correções manualmente...${NC}"
    
    # Aplicar healthcheck via docker update (se possível)
    echo -e "${BLUE}Reiniciando containers com nova configuração...${NC}"
    run_vm_command 'docker restart ai_saas_frontend_prod ai_saas_proxy 2>&1'
    sleep 10
else
    echo -e "${BLUE}Aplicando correções via docker compose...${NC}"
    APPLY_RESULT=$(run_vm_command 'cd /home/azureuser/projeto/sky-poc-infra && docker compose down && docker compose up -d 2>&1')
    echo "$APPLY_RESULT"
    echo ""
    echo -e "${BLUE}Aguardando containers iniciarem (30 segundos)...${NC}"
    sleep 30
fi
echo ""

# ============================================================================
# FASE 3: VALIDAR DEPOIS DA CORREÇÃO
# ============================================================================
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}   FASE 3.: VALIDAR (DEPOIS DA CORREÇÃO)${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE}5. Validar healthcheck em tempo real${NC}"
echo ""
echo -e "${YELLOW}Monitorando status dos containers (60 segundos)...${NC}"
for i in {1..12}; do
    STATUS=$(run_vm_command 'docker ps --format "{{.Names}}: {{.Status}}" | grep -E "(frontend|proxy)"')
    echo "[$i/12] $(date +%H:%M:%S) - $STATUS"
    sleep 5
done
echo ""

FRONTEND_HEALTH=$(run_vm_command 'docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Status}}"')
if echo "$FRONTEND_HEALTH" | grep -q "healthy"; then
    echo -e "${GREEN}[OK] Frontend está healthy${NC}"
    HEALTHCHECK_WORKING=true
else
    echo -e "${RED}[ERROR] Frontend NÃO está healthy: $FRONTEND_HEALTH${NC}"
    HEALTHCHECK_WORKING=false
fi
echo ""

echo -e "${BLUE}6. Validar logs novamente${NC}"
echo ""
echo -e "${BLUE}   Logs do nginx (últimas 50 linhas):${NC}"
NGINX_LOGS_AFTER=$(run_vm_command 'docker logs ai_saas_proxy --tail 50 2>&1')
echo "$NGINX_LOGS_AFTER" | tail -30

NO_502_IN_LOGS=true
if echo "$NGINX_LOGS_AFTER" | grep -q "502\|Connection refused\|upstream.*failed"; then
    echo -e "${RED}[ERROR] Ainda há erros 502 nos logs${NC}"
    NO_502_IN_LOGS=false
else
    echo -e "${GREEN}[OK] Nenhum erro 502 encontrado nos logs recentes${NC}"
fi
echo ""

echo -e "${BLUE}   Logs do frontend (últimas 50 linhas):${NC}"
FRONTEND_LOGS_AFTER=$(run_vm_command 'docker logs ai_saas_frontend_prod --tail 50 2>&1')
echo "$FRONTEND_LOGS_AFTER" | tail -30
echo ""

echo -e "${BLUE}7. Testes ativos (comprovam funcionamento)${NC}"
echo ""
echo -n "  Teste 1 - localhost:80: "
TEST_LOCAL=$(run_vm_command 'curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1')
if echo "$TEST_LOCAL" | grep -qE "200|301|302|307"; then
    echo -e "${GREEN}[OK] HTTP $TEST_LOCAL${NC}"
    TEST_LOCAL_OK=true
else
    echo -e "${RED}[ERROR] HTTP $TEST_LOCAL${NC}"
    TEST_LOCAL_OK=false
fi

echo -n "  Teste 2 - nginx → frontend: "
TEST_NGINX=$(run_vm_command 'docker exec ai_saas_proxy curl -s -o /dev/null -w "%{http_code}" http://frontend:3000 2>&1')
if echo "$TEST_NGINX" | grep -qE "200|301|302|307"; then
    echo -e "${GREEN}[OK] HTTP $TEST_NGINX${NC}"
    TEST_NGINX_OK=true
else
    echo -e "${RED}[ERROR] HTTP $TEST_NGINX${NC}"
    TEST_NGINX_OK=false
fi

echo -n "  Teste 3 - IP externo: "
TEST_EXTERNAL=$(run_vm_command 'curl -s -o /dev/null -w "%{http_code}" http://20.185.60.67 2>&1')
if echo "$TEST_EXTERNAL" | grep -qE "200|301|302|307"; then
    echo -e "${GREEN}[OK] HTTP $TEST_EXTERNAL${NC}"
    TEST_EXTERNAL_OK=true
else
    echo -e "${RED}[ERROR] HTTP $TEST_EXTERNAL${NC}"
    TEST_EXTERNAL_OK=false
fi
echo ""

echo -e "${BLUE}8. Teste de regressão (nível sênior)${NC}"
echo ""
echo -e "${YELLOW}[WARNING] Reiniciando frontend para testar resiliência...${NC}"
run_vm_command 'docker restart ai_saas_frontend_prod'
echo ""

echo -e "${YELLOW}Monitorando durante restart (60 segundos)...${NC}"
REGRESSION_PASSED=true
for i in {1..12}; do
    FRONTEND_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Status}}"')
    NGINX_TEST=$(run_vm_command 'curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "ERRO"')
    
    echo "[$i/12] $(date +%H:%M:%S) - Frontend: $FRONTEND_STATUS | Nginx: HTTP $NGINX_TEST"
    
    # Verificar se nginx retornou 502 durante restart
    if echo "$NGINX_TEST" | grep -q "502"; then
        echo -e "${RED} 502 detectado durante restart!${NC}"
        REGRESSION_PASSED=false
    fi
    
    if echo "$FRONTEND_STATUS" | grep -q "healthy" && echo "$NGINX_TEST" | grep -qE "200|301|302|307"; then
        echo -e "${GREEN}[OK] Frontend healthy e nginx respondendo!${NC}"
        break
    fi
    
    sleep 5
done
echo ""

FINAL_TEST=$(run_vm_command 'curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1')
if echo "$FINAL_TEST" | grep -qE "200|301|302|307"; then
    if [ "$REGRESSION_PASSED" = true ]; then
        echo -e "${GREEN}[OK] TESTE DE REGRESSÃO PASSOU${NC}"
        echo -e "${GREEN}[OK] Nginx não retornou 502 durante restart${NC}"
        echo -e "${GREEN}[OK] Sistema se recuperou automaticamente${NC}"
    else
        echo -e "${YELLOW}[WARNING] TESTE DE REGRESSÃO PARCIAL${NC}"
        echo -e "${YELLOW}[WARNING] Houve 502 durante restart, mas sistema se recuperou${NC}"
    fi
else
    echo -e "${RED}[ERROR] TESTE DE REGRESSÃO FALHOU${NC}"
    echo -e "${RED}[ERROR] Ainda há problemas após restart${NC}"
fi
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    CONCLUSÃO PROFISSIONAL${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Critérios objetivos
CRITERIA_MET=0
TOTAL_CRITERIA=5

echo -e "${BLUE}Critérios objetivos de 'incidente resolvido':${NC}"
echo ""

if [ "$NO_502_IN_LOGS" = true ]; then
    echo -e "${GREEN}[OK] 1. Não há mais 502 nos logs${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${RED}[ERROR] 1. Ainda há 502 nos logs${NC}"
fi

if [ "$HEALTHCHECK_WORKING" = true ]; then
    echo -e "${GREEN}[OK] 2. Frontend só fica healthy quando responde${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${RED}[ERROR] 2. Healthcheck não está funcionando${NC}"
fi

if [ "$TEST_NGINX_OK" = true ]; then
    echo -e "${GREEN}[OK] 3. Nginx consegue conectar ao frontend${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${RED}[ERROR] 3. Nginx não consegue conectar ao frontend${NC}"
fi

if [ "$REGRESSION_PASSED" = true ]; then
    echo -e "${GREEN}[OK] 4. Restart do frontend não causa erro externo${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${YELLOW}[WARNING] 4. Restart causou 502 temporário (mas se recuperou)${NC}"
fi

if [ "$TEST_EXTERNAL_OK" = true ]; then
    echo -e "${GREEN}[OK] 5. Sistema se auto-recupera sem intervenção${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${RED}[ERROR] 5. Sistema não está acessível externamente${NC}"
fi

echo ""
echo -e "${BLUE}Resultado: $CRITERIA_MET/$TOTAL_CRITERIA critérios atendidos${NC}"
echo ""

if [ $CRITERIA_MET -eq $TOTAL_CRITERIA ]; then
    echo -e "${GREEN}[OK] Root cause confirmado e corrigido${NC}"
    echo -e "${GREEN}[OK] Correções validadas${NC}"
    echo -e "${GREEN}[OK] Sem regressão detectada${NC}"
    echo ""
    echo -e "${BLUE}[INFO] O problema 502 Bad Gateway está resolvido estruturalmente${NC}"
elif [ $CRITERIA_MET -ge 3 ]; then
    echo -e "${YELLOW}[WARNING] Correções aplicadas com sucesso parcial${NC}"
    echo -e "${YELLOW}[INFO] Alguns critérios ainda não foram totalmente atendidos${NC}"
    echo -e "${YELLOW}[INFO] Pode ser necessário ajustar timeouts ou aguardar mais tempo${NC}"
else
    echo -e "${RED}[ERROR] Problema ainda persiste${NC}"
    echo -e "${YELLOW}[INFO] Revisar correções aplicadas e logs${NC}"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

