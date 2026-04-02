#!/bin/bash

# ==============================================================================
# SKY-POC :: SMOKE-TEST ENGINE (v1.0.0)
# ==============================================================================
# Propósito: Validar a saúde da aplicação pós-deploy (Post-Sync Hook).
# Objetivo: Garantir que Ingress + WAF + App + DB estão operacionais.
# ==============================================================================

set -euo pipefail

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configurações padrão (Podem ser sobrescritas via ENV)
MAX_RETRIES=${MAX_RETRIES:-3}
RETRY_DELAY=${RETRY_DELAY:-5}
TIMEOUT=${TIMEOUT:-10}
USER_AGENT="${SMOKE_TEST_UA:-SkySmokeTest/1.0 (DevOps-Engine)}"

# URLs padrão (Staging) se não informadas
BACKEND_URL=${BACKEND_URL:-"https://workspace-stg-api.skyfirstlabs.com/api/health"}
FRONTEND_URL=${FRONTEND_URL:-"https://workspace-stg.skyfirstlabs.com/"}

echo -e "${BLUE}================================================================${NC}"
echo -e "${BLUE}Starting Smoke Tests for Sky-POC${NC}"
echo -e "${BLUE}================================================================${NC}"
echo -e "User-Agent: $USER_AGENT"
echo -e "Max Retries: $MAX_RETRIES"
echo -e ""

# Função de log com timestamp
log() {
    echo -e "[$(date +'%Y-%m-%dT%H:%M:%S')] $1"
}

# Função de execução do teste com retry
run_test() {
    local name=$1
    local url=$2
    local expected_code=$3
    local retry_count=0
    local success=false

    log "${BLUE}Testing $name...${NC}"
    log "URL: $url"

    while [ $retry_count -lt $MAX_RETRIES ]; do
        # Executa o curl e captura o status code
        # -s: Silent
        # -o /dev/null: Descarta o corpo por enquanto
        # -I: Head request (melhor para performance) ou usar -w para pegar status
        
        RESPONSE=$(curl -L -s -o /dev/null -w "%{http_code}" \
            --user-agent "$USER_AGENT" \
            --connect-timeout "$TIMEOUT" \
            --max-time "$((TIMEOUT * 2))" \
            "$url")

        if [ "$RESPONSE" == "$expected_code" ]; then
            log "${GREEN}✓ Success: $name is UP (HTTP $RESPONSE)${NC}"
            success=true
            break
        else
            retry_count=$((retry_count + 1))
            log "${YELLOW}⚠ Warning: $name returned $RESPONSE. Attempt $retry_count of $MAX_RETRIES...${NC}"
            
            if [ $retry_count -lt $MAX_RETRIES ]; then
                sleep "$RETRY_DELAY"
            fi
        fi
    done

    if [ "$success" = false ]; then
        log "${RED}✗ Error: $name failed after $MAX_RETRIES attempts (Last code: $RESPONSE)${NC}"
        return 1
    fi
    return 0
}

# --- EXECUÇÃO DOS TESTES ---

EXIT_CODE=0

# 1. Validação do Backend (Ingress -> WAF -> App -> DB)
# Nota: Esperamos que o endpoint de health reflita o estado do DB também.
if ! run_test "Backend-API" "$BACKEND_URL" "200"; then
    EXIT_CODE=1
fi

echo ""

# 2. Validação do Frontend (Ingress -> WAF -> WebApp)
if ! run_test "Frontend-App" "$FRONTEND_URL" "200"; then
    EXIT_CODE=1
fi

# --- RESULTADO FINAL ---
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}================================================================${NC}"
    echo -e "${GREEN}SMOKE TESTS PASSED SUCCESSFULLY!${NC}"
    echo -e "${GREEN}================================================================${NC}"
else
    echo -e "${RED}================================================================${NC}"
    echo -e "${RED}SMOKE TESTS FAILED! CHECK LOGS ABOVE.${NC}"
    echo -e "${RED}================================================================${NC}"
    # Opcional: Adicionar alerta aqui (ex: Slack/Teams Webhook)
fi

exit $EXIT_CODE
