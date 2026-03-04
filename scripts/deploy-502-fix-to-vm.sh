#!/bin/bash
# Script para aplicar correção 502 na VM e executar validação completa
# Uso: ./scripts/deploy-502-fix-to-vm.sh [RESOURCE_GROUP] [VM_NAME]

set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"
VM_IP="${3:-20.185.60.67}"
SSH_KEY="${4:-keys/azure/team/id_rsa_poc}"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   🚀 Deploy Correção 502 Bad Gateway${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Resource Group: $RESOURCE_GROUP"
echo "VM Name: $VM_NAME"
echo "VM IP: $VM_IP"
echo ""

# Verificar se docker-compose.yml local tem healthcheck
if ! grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo -e "${RED}❌ Healthcheck não encontrado no docker-compose.yml local${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Healthcheck confirmado no docker-compose.yml local${NC}"
echo ""

# Verificar se chave SSH existe
if [ ! -f "$SSH_KEY" ]; then
    echo -e "${YELLOW}⚠️  Chave SSH não encontrada: $SSH_KEY${NC}"
    echo -e "${YELLOW}💡 Tentando usar Azure CLI Run Command...${NC}"
    USE_AZURE_CLI=true
else
    USE_AZURE_CLI=false
fi

# Função para executar comando via Azure CLI
run_azure_command() {
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
# PASSO 1: COPIAR DOCKER-COMPOSE.YML PARA VM
# ============================================================================
echo -e "${BLUE}1️⃣ Copiando docker-compose.yml atualizado para VM...${NC}"

if [ "$USE_AZURE_CLI" = false ]; then
    # Via SSH
    echo -e "${YELLOW}Usando SSH...${NC}"
    scp -i "$SSH_KEY" -o StrictHostKeyChecking=no docker-compose.yml "azureuser@$VM_IP:/tmp/docker-compose.yml" 2>&1
    run_azure_command "sudo mv /tmp/docker-compose.yml /home/azureuser/projeto/sky-poc-infra/docker-compose.yml && sudo chown azureuser:azureuser /home/azureuser/projeto/sky-poc-infra/docker-compose.yml" 2>&1 | tail -5
else
    # Via Azure CLI - ler arquivo e aplicar via script
    echo -e "${YELLOW}Usando Azure CLI...${NC}"
    DOCKER_COMPOSE_CONTENT=$(cat docker-compose.yml | base64)
    
    APPLY_SCRIPT=$(cat <<EOF
set -eu
cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || exit 1
echo "$DOCKER_COMPOSE_CONTENT" | base64 -d > docker-compose.yml.new
if grep -A 10 "frontend:" docker-compose.yml.new | grep -q "healthcheck:"; then
    mv docker-compose.yml docker-compose.yml.backup
    mv docker-compose.yml.new docker-compose.yml
    echo "✅ docker-compose.yml atualizado com healthcheck"
else
    echo "❌ Healthcheck não encontrado no arquivo"
    exit 1
fi
EOF
)
    
    run_azure_command "$APPLY_SCRIPT" 2>&1 | tail -10
fi

echo ""

# ============================================================================
# PASSO 2: COPIAR SCRIPT DE VALIDAÇÃO PARA VM
# ============================================================================
echo -e "${BLUE}2️⃣ Copiando script de validação para VM...${NC}"

VALIDATION_SCRIPT=$(cat scripts/apply-and-validate-502-fix.sh | base64)

DEPLOY_SCRIPT=$(cat <<'SCRIPT_EOF'
set -eu
cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || exit 1

# Decodificar script de validação
SCRIPT_EOF
echo "echo '$VALIDATION_SCRIPT' | base64 -d > scripts/apply-and-validate-502-fix.sh"
cat <<'SCRIPT_EOF'
chmod +x scripts/apply-and-validate-502-fix.sh
echo "✅ Script de validação copiado"
SCRIPT_EOF
)

# Substituir placeholder
DEPLOY_SCRIPT_FINAL=$(echo "$DEPLOY_SCRIPT" | sed "s|VALIDATION_SCRIPT|$VALIDATION_SCRIPT|g")

run_azure_command "$DEPLOY_SCRIPT_FINAL" 2>&1 | tail -5
echo ""

# ============================================================================
# PASSO 3: EXECUTAR VALIDAÇÃO COMPLETA
# ============================================================================
echo -e "${BLUE}3️⃣ Executando validação completa na VM...${NC}"
echo -e "${YELLOW}⚠️  Isso pode levar alguns minutos...${NC}"
echo ""

EXECUTE_SCRIPT=$(cat <<'EOF'
set -eu
cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || exit 1
./scripts/apply-and-validate-502-fix.sh
EOF
)

run_azure_command "$EXECUTE_SCRIPT" 2>&1

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Deploy concluído${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}💡 Verifique o output acima para confirmar que todos os critérios foram atendidos${NC}"
echo -e "${BLUE}💡 A plataforma deve estar acessível em: http://$VM_IP${NC}"
echo ""

