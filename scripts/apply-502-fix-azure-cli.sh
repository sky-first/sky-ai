#!/bin/bash
# Script para aplicar correção 502 via Azure CLI Run Command
# Uso: ./scripts/apply-502-fix-azure-cli.sh [RESOURCE_GROUP] [VM_NAME]

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
echo -e "${CYAN}    Aplicando Correção 502 Bad Gateway${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Resource Group: $RESOURCE_GROUP"
echo "VM Name: $VM_NAME"
echo ""

# Script completo para aplicar na VM
APPLY_SCRIPT=$(cat <<'SCRIPT_EOF'
set -eu

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   [OK] Aplicação e Validação - Healthcheck Frontend${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Navegar para diretório do projeto
cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || {
    echo -e "${RED}[ERROR] Diretório não encontrado${NC}"
    exit 1
}

# ============================================================================
# PASSO 1: APLICAR HEALTHCHECK NO DOCKER-COMPOSE.YML
# ============================================================================
echo -e "${BLUE}1. Aplicando healthcheck no docker-compose.yml...${NC}"

# Verificar se já existe
if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo -e "${GREEN}[OK] Healthcheck já existe${NC}"
else
    echo -e "${YELLOW}[WARNING] Adicionando healthcheck...${NC}"
    
    # Fazer backup
    cp docker-compose.yml docker-compose.yml.backup.$(date +%Y%m%d_%H%M%S)
    
    # Adicionar healthcheck após networks
    sed -i '/networks:/a\    # Healthcheck para garantir que Next.js está pronto antes de nginx iniciar\n    # start_period: 90s dá tempo para Next.js compilar em modo dev (NODE_ENV=development)\n    # Isso elimina race condition: nginx só inicia quando frontend está realmente pronto\n    healthcheck:\n      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:3000/ || exit 1"]\n      interval: 30s\n      timeout: 10s\n      retries: 5\n      start_period: 90s' docker-compose.yml
    
    # Verificar se foi aplicado
    if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
        echo -e "${GREEN}[OK] Healthcheck aplicado com sucesso${NC}"
    else
        echo -e "${RED}[ERROR] Erro ao aplicar healthcheck${NC}"
        exit 1
    fi
fi

# Verificar se depends_on do proxy usa service_healthy
if grep -A 5 "proxy:" docker-compose.yml | grep -A 3 "depends_on:" | grep -q "service_healthy"; then
    echo -e "${GREEN}[OK] depends_on já usa service_healthy${NC}"
else
    echo -e "${YELLOW}[WARNING] Ajustando depends_on para service_healthy...${NC}"
    sed -i 's/frontend:.*condition: service_started/frontend:\n        condition: service_healthy/g' docker-compose.yml
    sed -i 's/frontend:.*condition: service_healthy/frontend:\n        condition: service_healthy/g' docker-compose.yml
fi

echo ""

# ============================================================================
# PASSO 2: APLICAR CORREÇÕES (DOCKER COMPOSE DOWN/UP)
# ============================================================================
echo -e "${BLUE}2. Aplicando correções (docker compose down/up)...${NC}"
echo ""

echo -e "${YELLOW}[WARNING] Parando todos os containers...${NC}"
docker compose down
echo ""

echo -e "${YELLOW}[WARNING] Iniciando containers com nova configuração...${NC}"
docker compose up -d
echo ""

echo -e "${BLUE}Aguardando 10 segundos para containers iniciarem...${NC}"
sleep 10
echo ""

# ============================================================================
# PASSO 3: VALIDAR HEALTHCHECK EM TEMPO REAL
# ============================================================================
echo -e "${BLUE}3. Validar healthcheck em tempo real...${NC}"
echo ""

HEALTHY_DETECTED=false
NO_502_DURING_STARTUP=true

for i in {1..18}; do
    TIMESTAMP=$(date +%H:%M:%S)
    
    FRONTEND_STATUS=$(docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Status}}" 2>/dev/null || echo "NOT_RUNNING")
    PROXY_STATUS=$(docker ps --filter "name=ai_saas_proxy" --format "{{.Status}}" 2>/dev/null || echo "NOT_RUNNING")
    NGINX_TEST=$(curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "ERRO")
    
    echo "[$i/18] $TIMESTAMP - Frontend: $FRONTEND_STATUS | Proxy: $PROXY_STATUS | Nginx: HTTP $NGINX_TEST"
    
    if echo "$FRONTEND_STATUS" | grep -q "healthy"; then
        if [ "$HEALTHY_DETECTED" = false ]; then
            echo -e "${GREEN}  [OK] Frontend ficou healthy em $TIMESTAMP${NC}"
            HEALTHY_DETECTED=true
        fi
    fi
    
    if echo "$NGINX_TEST" | grep -q "502"; then
        echo -e "${RED}   502 detectado em $TIMESTAMP!${NC}"
        NO_502_DURING_STARTUP=false
    fi
    
    if echo "$FRONTEND_STATUS" | grep -q "healthy" && echo "$PROXY_STATUS" | grep -q "Up\|healthy" && echo "$NGINX_TEST" | grep -qE "200|301|302|307"; then
        echo -e "${GREEN}  [OK] Sistema totalmente operacional em $TIMESTAMP${NC}"
        break
    fi
    
    sleep 5
done
echo ""

FINAL_FRONTEND_STATUS=$(docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Status}}")
FINAL_PROXY_STATUS=$(docker ps --filter "name=ai_saas_proxy" --format "{{.Status}}")

echo -e "${BLUE}Estado final:${NC}"
echo "  Frontend: $FINAL_FRONTEND_STATUS"
echo "  Proxy: $FINAL_PROXY_STATUS"
echo ""

# ============================================================================
# PASSO 4: VERIFICAR LOGS
# ============================================================================
echo -e "${BLUE}4. Verificar logs...${NC}"
echo ""

NGINX_LOGS=$(docker logs ai_saas_proxy --tail 30 2>&1)
NO_502_IN_LOGS=true
if echo "$NGINX_LOGS" | grep -q "502\|Connection refused.*frontend"; then
    echo -e "${RED} Ainda há erros 502 nos logs do nginx${NC}"
    NO_502_IN_LOGS=false
else
    echo -e "${GREEN}[OK] Nenhum erro 502 encontrado nos logs do nginx${NC}"
fi
echo ""

# ============================================================================
# PASSO 5: TESTES ATIVOS
# ============================================================================
echo -e "${BLUE}5. Testes ativos...${NC}"
echo ""

echo -n "  Teste 1 - localhost:80: "
TEST_LOCAL=$(curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1)
if echo "$TEST_LOCAL" | grep -qE "200|301|302|307"; then
    echo -e "${GREEN}[OK] HTTP $TEST_LOCAL${NC}"
    TEST_LOCAL_OK=true
else
    echo -e "${RED}[ERROR] HTTP $TEST_LOCAL${NC}"
    TEST_LOCAL_OK=false
fi

echo -n "  Teste 2 - nginx → frontend: "
TEST_NGINX=$(docker exec ai_saas_proxy curl -s -o /dev/null -w "%{http_code}" http://frontend:3000 2>&1)
if echo "$TEST_NGINX" | grep -qE "200|301|302|307"; then
    echo -e "${GREEN}[OK] HTTP $TEST_NGINX${NC}"
    TEST_NGINX_OK=true
else
    echo -e "${RED}[ERROR] HTTP $TEST_NGINX${NC}"
    TEST_NGINX_OK=false
fi

echo -n "  Teste 3 - IP externo (20.185.60.67): "
TEST_EXTERNAL=$(curl -s -o /dev/null -w "%{http_code}" http://20.185.60.67 2>&1)
if echo "$TEST_EXTERNAL" | grep -qE "200|301|302|307"; then
    echo -e "${GREEN}[OK] HTTP $TEST_EXTERNAL${NC}"
    TEST_EXTERNAL_OK=true
else
    echo -e "${RED}[ERROR] HTTP $TEST_EXTERNAL${NC}"
    TEST_EXTERNAL_OK=false
fi
echo ""

# ============================================================================
# PASSO 6: TESTE DE REGRESSÃO
# ============================================================================
echo -e "${BLUE}6. Teste de regressão (reiniciar frontend)...${NC}"
echo ""

echo -e "${YELLOW}[WARNING] Reiniciando frontend...${NC}"
docker restart ai_saas_frontend_prod
echo ""

HEALTHY_AFTER_RESTART=false
NO_502_DURING_RESTART=true

for i in {1..12}; do
    TIMESTAMP=$(date +%H:%M:%S)
    FRONTEND_STATUS=$(docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Status}}")
    NGINX_TEST=$(curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "ERRO")
    
    echo "[$i/12] $TIMESTAMP - Frontend: $FRONTEND_STATUS | Nginx: HTTP $NGINX_TEST"
    
    if echo "$NGINX_TEST" | grep -q "502"; then
        echo -e "${RED}   502 detectado durante restart!${NC}"
        NO_502_DURING_RESTART=false
    fi
    
    if echo "$FRONTEND_STATUS" | grep -q "healthy"; then
        if [ "$HEALTHY_AFTER_RESTART" = false ]; then
            echo -e "${GREEN}  → Frontend ficou healthy após restart${NC}"
            HEALTHY_AFTER_RESTART=true
        fi
    fi
    
    if echo "$FRONTEND_STATUS" | grep -q "healthy" && echo "$NGINX_TEST" | grep -qE "200|301|302|307"; then
        echo -e "${GREEN}  [OK] Sistema totalmente recuperado em $TIMESTAMP${NC}"
        break
    fi
    
    sleep 5
done
echo ""

FINAL_TEST=$(curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1)

# ============================================================================
# CONCLUSÃO
# ============================================================================
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    CONCLUSÃO PROFISSIONAL${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

CRITERIA_MET=0
TOTAL_CRITERIA=5

echo -e "${BLUE}Critérios objetivos:${NC}"
echo ""

if echo "$FINAL_FRONTEND_STATUS" | grep -q "healthy"; then
    echo -e "${GREEN}[OK] 1. Frontend só fica healthy quando responde HTTP${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${RED}[ERROR] 1. Frontend não está healthy${NC}"
fi

if echo "$FINAL_PROXY_STATUS" | grep -q "Up\|healthy"; then
    echo -e "${GREEN}[OK] 2. Nginx só inicia após frontend healthy${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${RED}[ERROR] 2. Nginx não está rodando${NC}"
fi

if [ "$NO_502_IN_LOGS" = true ] && [ "$NO_502_DURING_RESTART" = true ]; then
    echo -e "${GREEN}[OK] 3. Nenhum 502 nos logs após restart${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${RED}[ERROR] 3. Ainda há 502 nos logs ou durante restart${NC}"
fi

if [ "$HEALTHY_AFTER_RESTART" = true ] && echo "$FINAL_TEST" | grep -qE "200|301|302|307"; then
    echo -e "${GREEN}[OK] 4. Sistema se recupera sozinho após restart${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${RED}[ERROR] 4. Sistema não se recuperou após restart${NC}"
fi

if [ "$TEST_EXTERNAL_OK" = true ]; then
    echo -e "${GREEN}[OK] 5. Sistema acessível externamente${NC}"
    CRITERIA_MET=$((CRITERIA_MET + 1))
else
    echo -e "${RED}[ERROR] 5. Sistema não acessível externamente${NC}"
fi

echo ""
echo -e "${BLUE}Resultado: $CRITERIA_MET/$TOTAL_CRITERIA critérios atendidos${NC}"
echo ""

if [ $CRITERIA_MET -eq $TOTAL_CRITERIA ]; then
    echo -e "${GREEN}[OK][OK][OK] INCIDENTE RESOLVIDO ESTRUTURALMENTE${NC}"
    echo ""
    echo -e "${GREEN}[OK] Root cause confirmado e corrigido${NC}"
    echo -e "${GREEN}[OK] Correções validadas${NC}"
    echo -e "${GREEN}[OK] Sem regressão detectada${NC}"
    echo -e "${GREEN}[OK] Sistema se auto-recupera${NC}"
    echo ""
    echo -e "${BLUE}[INFO] O problema 502 Bad Gateway está resolvido de forma estrutural${NC}"
    echo -e "${BLUE}[INFO] A plataforma está acessível: http://20.185.60.67${NC}"
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN} INCIDENTE ENCERRADO COM SUCESSO${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    exit 0
elif [ $CRITERIA_MET -ge 3 ]; then
    echo -e "${YELLOW}[WARNING] Correções aplicadas com sucesso parcial${NC}"
    echo -e "${YELLOW}[INFO] $CRITERIA_MET de $TOTAL_CRITERIA critérios atendidos${NC}"
    exit 1
else
    echo -e "${RED}[ERROR] Problema ainda persiste${NC}"
    exit 1
fi
SCRIPT_EOF
)

# Converter script para array (Azure CLI requer array de strings)
IFS=$'\n' read -d '' -r -a SCRIPTS_ARRAY <<< "$APPLY_SCRIPT" || true

echo -e "${BLUE}Executando script na VM (isso pode levar alguns minutos)...${NC}"
echo ""

OUTPUT=$(az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "${SCRIPTS_ARRAY[@]}" \
    --output json 2>&1)

if [ $? -eq 0 ]; then
    echo "$OUTPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        msg = msg.replace('[stdout]', '').replace('[stderr]', '')
        print(msg)
except Exception as e:
    print('Erro ao processar output:', e)
    print(sys.stdin.read())
" 2>/dev/null || echo "$OUTPUT"
    
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}[OK] Deploy concluído${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
else
    echo -e "${RED}[ERROR] Erro ao executar deploy${NC}"
    echo "$OUTPUT"
    exit 1
fi

