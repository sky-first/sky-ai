#!/bin/bash
# Script de Verificação Completa - Frontend e Backend
# Executa diagnóstico completo e gera relatório detalhado
# Uso: ./scripts/verify-connection-complete.sh [VM_IP]

set -eu

VM_IP="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Contadores
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0
WARNING_CHECKS=0

# Funções de log
log_section() {
    echo ""
    echo "=========================================="
    echo -e "${CYAN}$1${NC}"
    echo "=========================================="
    echo ""
}

log_check() {
    local status="$1"
    local message="$2"
    ((TOTAL_CHECKS++))
    
    case "$status" in
        "PASS")
            echo -e "${GREEN}[OK] PASS${NC}: $message"
            ((PASSED_CHECKS++))
            ;;
        "FAIL")
            echo -e "${RED}[ERROR] FAIL${NC}: $message"
            ((FAILED_CHECKS++))
            ;;
        "WARN")
            echo -e "${YELLOW}[WARNING] WARN${NC}: $message"
            ((WARNING_CHECKS++))
            ;;
        "INFO")
            echo -e "${BLUE}ℹ️  INFO${NC}: $message"
            ;;
    esac
}

test_http() {
    local url="$1"
    local expected_status="${2:-200}"
    local timeout="${3:-10}"
    
    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$timeout" --connect-timeout 5 "$url" 2>/dev/null || echo "000")
    
    if [ "$response" = "$expected_status" ]; then
        return 0
    elif [ "$response" = "000" ]; then
        return 2
    else
        return 1
    fi
}

# Verificar se IP foi fornecido
if [ -z "$VM_IP" ]; then
    log_section "🔍 Tentando Obter IP da VM Automaticamente"
    
    # Tentar via Terraform
    if [ -d "$PROJECT_DIR/infra/azure" ]; then
        cd "$PROJECT_DIR/infra/azure"
        VM_IP=$(terraform output -raw vm_public_ip 2>/dev/null || echo "")
        cd "$PROJECT_DIR"
    fi
    
    # Tentar via Azure CLI
    if [ -z "$VM_IP" ]; then
        VM_IP=$(az vm list-ip-addresses --query "[?contains(name, 'poc-sky') || contains(name, 'ai-saas')].virtualMachine.network.publicIpAddresses[0].ipAddress" -o tsv 2>/dev/null | head -1 || echo "")
    fi
    
    if [ -z "$VM_IP" ]; then
        echo -e "${RED}[ERROR] ERRO: IP da VM não fornecido e não foi possível obter automaticamente${NC}"
        echo ""
        echo "Forneça o IP manualmente:"
        echo "  $0 <VM_IP>"
        echo ""
        echo "Ou obtenha o IP via:"
        echo "  1. GitHub Actions → Terraform Apply → vm_public_ip"
        echo "  2. Azure Portal → Resource Groups → Public IP addresses"
        echo "  3. Azure CLI: az vm show -d -g <rg> -n <vm> --query publicIps"
        exit 1
    fi
fi

echo "=========================================="
echo -e "${CYAN}🔍 VERIFICAÇÃO COMPLETA - FRONTEND/BACKEND${NC}"
echo "=========================================="
echo ""
echo "VM IP: $VM_IP"
echo "Data/Hora: $(date)"
echo ""

# ============================================
# PARTE 1: ANÁLISE ESTÁTICA DO CÓDIGO
# ============================================
log_section "📋 PARTE 1: ANÁLISE ESTÁTICA DO CÓDIGO"

echo "Verificando configurações arquiteturais..."
echo ""

# 1.1 Verificar docker-compose.yml
log_check "INFO" "Analisando docker-compose.yml..."

# Backend service
if grep -q "^  backend:" "$PROJECT_DIR/docker-compose.yml"; then
    log_check "PASS" "Serviço 'backend' definido no docker-compose.yml"
    
    # Verificar build context
    if grep -A 3 "^  backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "context: ../sky-poc-backend"; then
        log_check "PASS" "Backend build context: ../sky-poc-backend"
    else
        log_check "FAIL" "Backend build context não encontrado ou incorreto"
    fi
    
    # Verificar porta
    if grep -A 20 "^  backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "port 8000\|:8000"; then
        log_check "PASS" "Backend configurado para porta 8000"
    else
        log_check "WARN" "Porta do backend não explicitamente definida (usando padrão)"
    fi
    
    # Verificar health check
    if grep -A 30 "^  backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "healthcheck:"; then
        log_check "PASS" "Backend tem health check configurado"
    else
        log_check "FAIL" "Backend não tem health check configurado"
    fi
else
    log_check "FAIL" "Serviço 'backend' não encontrado no docker-compose.yml"
fi

# Frontend service
if grep -q "^  frontend:" "$PROJECT_DIR/docker-compose.yml"; then
    log_check "PASS" "Serviço 'frontend' definido no docker-compose.yml"
    
    # Verificar build context
    if grep -A 3 "^  frontend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "context: ../sky-poc-frontend"; then
        log_check "PASS" "Frontend build context: ../sky-poc-frontend"
    else
        log_check "FAIL" "Frontend build context não encontrado ou incorreto"
    fi
    
    # Verificar NEXT_PUBLIC_API_URL
    if grep -A 10 "^  frontend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "NEXT_PUBLIC_API_URL"; then
        log_check "PASS" "NEXT_PUBLIC_API_URL configurado no frontend"
        NEXT_PUBLIC_API_URL_VALUE=$(grep -A 10 "^  frontend:" "$PROJECT_DIR/docker-compose.yml" | grep "NEXT_PUBLIC_API_URL" | head -1)
        if echo "$NEXT_PUBLIC_API_URL_VALUE" | grep -q "localhost:8000"; then
            log_check "WARN" "NEXT_PUBLIC_API_URL usa localhost (pode estar incorreto para produção)"
        else
            log_check "PASS" "NEXT_PUBLIC_API_URL não usa localhost"
        fi
    else
        log_check "FAIL" "NEXT_PUBLIC_API_URL não configurado no frontend"
    fi
    
    # Verificar dependências
    if grep -A 15 "^  frontend:" "$PROJECT_DIR/docker-compose.yml" | grep -A 5 "depends_on:" | grep -q "backend:"; then
        log_check "PASS" "Frontend depende de backend"
        if grep -A 15 "^  frontend:" "$PROJECT_DIR/docker-compose.yml" | grep -A 5 "depends_on:" | grep -q "condition: service_healthy"; then
            log_check "PASS" "Frontend aguarda backend estar healthy"
        else
            log_check "WARN" "Frontend não aguarda backend estar healthy (pode iniciar antes)"
        fi
    else
        log_check "FAIL" "Frontend não depende de backend"
    fi
else
    log_check "FAIL" "Serviço 'frontend' não encontrado no docker-compose.yml"
fi

# Proxy service
if grep -q "^  proxy:" "$PROJECT_DIR/docker-compose.yml"; then
    log_check "PASS" "Serviço 'proxy' definido no docker-compose.yml"
    
    # Verificar dependências
    if grep -A 10 "^  proxy:" "$PROJECT_DIR/docker-compose.yml" | grep -A 5 "depends_on:" | grep -qE "backend:|frontend:"; then
        log_check "PASS" "Proxy depende de backend e/ou frontend"
    else
        log_check "WARN" "Proxy não tem dependências explícitas"
    fi
    
    # Verificar volumes (nginx config)
    if grep -A 15 "^  proxy:" "$PROJECT_DIR/docker-compose.yml" | grep -q "nginx.conf"; then
        log_check "PASS" "Proxy monta configuração do nginx"
    else
        log_check "FAIL" "Proxy não monta configuração do nginx"
    fi
else
    log_check "FAIL" "Serviço 'proxy' não encontrado no docker-compose.yml"
fi

# Rede Docker
if grep -q "ai_saas_network" "$PROJECT_DIR/docker-compose.yml"; then
    log_check "PASS" "Rede 'ai_saas_network' definida"
    NETWORK_COUNT=$(grep -c "ai_saas_network" "$PROJECT_DIR/docker-compose.yml" || echo "0")
    if [ "$NETWORK_COUNT" -ge 3 ]; then
        log_check "PASS" "Múltiplos serviços na mesma rede ($NETWORK_COUNT referências)"
    else
        log_check "WARN" "Poucos serviços na rede ($NETWORK_COUNT referências)"
    fi
else
    log_check "FAIL" "Rede 'ai_saas_network' não encontrada"
fi

echo ""

# 1.2 Verificar nginx.conf
log_check "INFO" "Analisando configuração do Nginx..."

if [ -f "$PROJECT_DIR/docker/nginx/nginx.conf" ]; then
    log_check "PASS" "Arquivo nginx.conf existe"
    
    # Verificar roteamento para frontend
    if grep -A 5 "location / {" "$PROJECT_DIR/docker/nginx/nginx.conf" | grep -q "proxy_pass.*frontend:3000"; then
        log_check "PASS" "Nginx roteia / para frontend:3000"
    else
        log_check "FAIL" "Nginx não roteia / para frontend:3000"
    fi
    
    # Verificar roteamento para backend
    if grep -A 10 "location /api/v1/" "$PROJECT_DIR/docker/nginx/nginx.conf" | grep -q "proxy_pass.*backend:8000"; then
        log_check "PASS" "Nginx roteia /api/v1/ para backend:8000"
        
        # Verificar se preserva path
        PROXY_PASS_LINE=$(grep -A 10 "location /api/v1/" "$PROJECT_DIR/docker/nginx/nginx.conf" | grep "proxy_pass" | head -1)
        if echo "$PROXY_PASS_LINE" | grep -q "backend:8000[^/]"; then
            log_check "PASS" "proxy_pass preserva path completo (/api/v1/users → backend:8000/api/v1/users)"
        else
            log_check "WARN" "proxy_pass pode não preservar path corretamente"
        fi
    else
        log_check "FAIL" "Nginx não roteia /api/v1/ para backend:8000"
    fi
    
    # Verificar CORS
    if grep -q "map.*cors_origin" "$PROJECT_DIR/docker/nginx/nginx.conf"; then
        log_check "PASS" "Map de CORS configurado"
        
        # Verificar origens permitidas
        if grep -A 10 "map.*cors_origin" "$PROJECT_DIR/docker/nginx/nginx.conf" | grep -qE "localhost|127.0.0.1"; then
            log_check "PASS" "CORS permite localhost"
        fi
        
        # Verificar se permite IP da VM
        if grep -A 10 "map.*cors_origin" "$PROJECT_DIR/docker/nginx/nginx.conf" | grep -qE "[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}"; then
            log_check "PASS" "CORS permite IPs específicos"
        else
            log_check "WARN" "CORS pode não permitir IP da VM (só localhost)"
        fi
    else
        log_check "WARN" "Map de CORS não encontrado"
    fi
    
    # Verificar headers CORS
    if grep -A 10 "location /api/v1/" "$PROJECT_DIR/docker/nginx/nginx.conf" | grep -q "Access-Control-Allow-Origin"; then
        log_check "PASS" "Headers CORS adicionados em /api/v1/"
    else
        log_check "FAIL" "Headers CORS não encontrados em /api/v1/"
    fi
    
    # Verificar HTTPS redirect
    if grep -q "return 301 https" "$PROJECT_DIR/docker/nginx/nginx.conf"; then
        log_check "WARN" "Nginx redireciona HTTP → HTTPS (verificar se certificados estão configurados)"
    else
        log_check "PASS" "Nginx não redireciona para HTTPS (ou está usando HTTP-only)"
    fi
else
    log_check "FAIL" "Arquivo nginx.conf não encontrado"
fi

echo ""

# 1.3 Verificar scripts de configuração
log_check "INFO" "Analisando scripts de configuração..."

# ensure-complete-env.sh
if [ -f "$PROJECT_DIR/scripts/azure/ensure-complete-env.sh" ]; then
    log_check "PASS" "Script ensure-complete-env.sh existe"
    if grep -q "NEXT_PUBLIC_API_URL" "$PROJECT_DIR/scripts/azure/ensure-complete-env.sh"; then
        log_check "PASS" "ensure-complete-env.sh configura NEXT_PUBLIC_API_URL"
    else
        log_check "FAIL" "ensure-complete-env.sh não configura NEXT_PUBLIC_API_URL"
    fi
else
    log_check "WARN" "Script ensure-complete-env.sh não encontrado"
fi

# deploy-via-azure-cli.sh
if [ -f "$PROJECT_DIR/scripts/azure/deploy-via-azure-cli.sh" ]; then
    log_check "PASS" "Script deploy-via-azure-cli.sh existe"
    if grep -q "NEXT_PUBLIC_API_URL" "$PROJECT_DIR/scripts/azure/deploy-via-azure-cli.sh"; then
        log_check "PASS" "deploy-via-azure-cli.sh configura NEXT_PUBLIC_API_URL"
    else
        log_check "WARN" "deploy-via-azure-cli.sh não configura NEXT_PUBLIC_API_URL"
    fi
else
    log_check "WARN" "Script deploy-via-azure-cli.sh não encontrado"
fi

# validate-env.sh
if [ -f "$PROJECT_DIR/scripts/validate-env.sh" ]; then
    log_check "PASS" "Script validate-env.sh existe"
    if grep -q "NEXT_PUBLIC_API_URL" "$PROJECT_DIR/scripts/validate-env.sh"; then
        log_check "PASS" "validate-env.sh valida NEXT_PUBLIC_API_URL"
    else
        log_check "WARN" "validate-env.sh não valida NEXT_PUBLIC_API_URL"
    fi
else
    log_check "WARN" "Script validate-env.sh não encontrado"
fi

echo ""

# ============================================
# PARTE 2: TESTES DE CONECTIVIDADE
# ============================================
log_section "🌐 PARTE 2: TESTES DE CONECTIVIDADE"

echo "Testando conectividade com a VM..."
echo ""

# 2.1 Porta 80
log_check "INFO" "Testando porta 80..."
if timeout 5 bash -c "echo > /dev/tcp/$VM_IP/80" 2>/dev/null; then
    log_check "PASS" "Porta 80 acessível"
else
    log_check "FAIL" "Porta 80 não acessível"
fi

# 2.2 Nginx/Frontend (raiz)
log_check "INFO" "Testando Nginx/Frontend (/)..."
if test_http "http://$VM_IP/" "200" 10; then
    log_check "PASS" "Frontend responde (HTTP 200)"
    FRONTEND_RESPONSE=$(curl -s --max-time 10 "http://$VM_IP/" 2>/dev/null || echo "")
    if echo "$FRONTEND_RESPONSE" | grep -qiE "(html|<!DOCTYPE|next|react)"; then
        log_check "PASS" "Frontend retorna HTML válido"
    else
        log_check "WARN" "Frontend pode não estar retornando HTML válido"
    fi
elif [ $? -eq 2 ]; then
    log_check "FAIL" "Frontend não responde (timeout/conexão recusada)"
else
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://$VM_IP/" 2>/dev/null || echo "000")
    log_check "WARN" "Frontend retornou HTTP $HTTP_CODE (esperado 200)"
fi

# 2.3 Backend Health Check
log_check "INFO" "Testando Backend Health Check (/health)..."
if test_http "http://$VM_IP/health" "200" 10; then
    log_check "PASS" "Backend Health Check responde (HTTP 200)"
    HEALTH_RESPONSE=$(curl -s --max-time 10 "http://$VM_IP/health" 2>/dev/null || echo "")
    if [ -n "$HEALTH_RESPONSE" ]; then
        log_check "PASS" "Backend Health Check retornou resposta: $(echo "$HEALTH_RESPONSE" | head -c 50)"
    else
        log_check "WARN" "Backend Health Check retornou resposta vazia"
    fi
elif [ $? -eq 2 ]; then
    log_check "FAIL" "Backend Health Check não responde (timeout/conexão recusada)"
else
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://$VM_IP/health" 2>/dev/null || echo "000")
    log_check "WARN" "Backend Health Check retornou HTTP $HTTP_CODE (esperado 200)"
fi

# 2.4 API Health Check
log_check "INFO" "Testando API Health Check (/api/v1/health)..."
if test_http "http://$VM_IP/api/v1/health" "200" 10; then
    log_check "PASS" "API Health Check responde (HTTP 200)"
    API_HEALTH_RESPONSE=$(curl -s --max-time 10 "http://$VM_IP/api/v1/health" 2>/dev/null || echo "")
    if [ -n "$API_HEALTH_RESPONSE" ]; then
        log_check "PASS" "API Health Check retornou resposta: $(echo "$API_HEALTH_RESPONSE" | head -c 50)"
    else
        log_check "WARN" "API Health Check retornou resposta vazia"
    fi
elif [ $? -eq 2 ]; then
    log_check "FAIL" "API Health Check não responde (timeout/conexão recusada)"
else
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://$VM_IP/api/v1/health" 2>/dev/null || echo "000")
    log_check "WARN" "API Health Check retornou HTTP $HTTP_CODE (esperado 200)"
fi

# 2.5 API Base
log_check "INFO" "Testando API Base (/api/v1/)..."
if test_http "http://$VM_IP/api/v1/" "200" 10; then
    log_check "PASS" "API Base responde (HTTP 200)"
elif test_http "http://$VM_IP/api/v1/" "404" 10; then
    log_check "PASS" "API Base responde (HTTP 404 - OK se não tiver rota raiz)"
elif test_http "http://$VM_IP/api/v1/" "405" 10; then
    log_check "PASS" "API Base responde (HTTP 405 - OK se método não permitido)"
elif [ $? -eq 2 ]; then
    log_check "FAIL" "API Base não responde (timeout/conexão recusada)"
else
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://$VM_IP/api/v1/" 2>/dev/null || echo "000")
    log_check "WARN" "API Base retornou HTTP $HTTP_CODE"
fi

echo ""

# ============================================
# PARTE 3: TESTES DE CORS
# ============================================
log_section "🔐 PARTE 3: TESTES DE CORS"

# 3.1 CORS Preflight (OPTIONS)
log_check "INFO" "Testando CORS Preflight (OPTIONS)..."
CORS_OPTIONS_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -X OPTIONS \
    -H "Origin: http://$VM_IP" \
    -H "Access-Control-Request-Method: GET" \
    --max-time 10 \
    "http://$VM_IP/api/v1/health" 2>/dev/null || echo "000")

if [ "$CORS_OPTIONS_RESPONSE" = "204" ] || [ "$CORS_OPTIONS_RESPONSE" = "200" ]; then
    log_check "PASS" "CORS Preflight funcionando (HTTP $CORS_OPTIONS_RESPONSE)"
else
    log_check "WARN" "CORS Preflight retornou HTTP $CORS_OPTIONS_RESPONSE (esperado 204 ou 200)"
fi

# 3.2 CORS Headers
log_check "INFO" "Verificando headers CORS..."
CORS_HEADERS=$(curl -s -I --max-time 10 \
    -H "Origin: http://$VM_IP" \
    "http://$VM_IP/api/v1/health" 2>/dev/null || echo "")

if echo "$CORS_HEADERS" | grep -qi "Access-Control-Allow-Origin"; then
    log_check "PASS" "Header Access-Control-Allow-Origin presente"
    CORS_ORIGIN_HEADER=$(echo "$CORS_HEADERS" | grep -i "Access-Control-Allow-Origin" | head -1)
    log_check "INFO" "  Valor: $CORS_ORIGIN_HEADER"
    
    if echo "$CORS_ORIGIN_HEADER" | grep -q "http://$VM_IP"; then
        log_check "PASS" "CORS permite origem do IP da VM"
    elif echo "$CORS_ORIGIN_HEADER" | grep -q "*"; then
        log_check "WARN" "CORS permite qualquer origem (*) - risco de segurança"
    elif echo "$CORS_ORIGIN_HEADER" | grep -q "localhost"; then
        log_check "WARN" "CORS só permite localhost (pode bloquear requisições do IP da VM)"
    else
        log_check "WARN" "CORS pode não permitir origem do IP da VM"
    fi
else
    log_check "FAIL" "Header Access-Control-Allow-Origin não encontrado"
fi

if echo "$CORS_HEADERS" | grep -qi "Access-Control-Allow-Methods"; then
    log_check "PASS" "Header Access-Control-Allow-Methods presente"
else
    log_check "WARN" "Header Access-Control-Allow-Methods não encontrado"
fi

if echo "$CORS_HEADERS" | grep -qi "Access-Control-Allow-Headers"; then
    log_check "PASS" "Header Access-Control-Allow-Headers presente"
else
    log_check "WARN" "Header Access-Control-Allow-Headers não encontrado"
fi

echo ""

# ============================================
# PARTE 4: VERIFICAÇÃO DE ROTEAMENTO
# ============================================
log_section "🔄 PARTE 4: VERIFICAÇÃO DE ROTEAMENTO"

# 4.1 Verificar se /api/v1/ roteia para backend
log_check "INFO" "Verificando roteamento /api/v1/ → backend..."
API_RESPONSE=$(curl -s --max-time 10 "http://$VM_IP/api/v1/health" 2>/dev/null || echo "")
if [ -n "$API_RESPONSE" ]; then
    log_check "PASS" "Roteamento /api/v1/ está funcionando (backend respondeu)"
    
    # Verificar se resposta parece ser do backend
    if echo "$API_RESPONSE" | grep -qiE "(status|ok|healthy|fastapi|api)"; then
        log_check "PASS" "Resposta parece ser do backend (contém palavras-chave da API)"
    else
        log_check "WARN" "Resposta pode não ser do backend esperado"
    fi
else
    log_check "FAIL" "Roteamento /api/v1/ não está funcionando (sem resposta)"
fi

# 4.2 Verificar se / roteia para frontend
log_check "INFO" "Verificando roteamento / → frontend..."
ROOT_RESPONSE=$(curl -s --max-time 10 "http://$VM_IP/" 2>/dev/null || echo "")
if [ -n "$ROOT_RESPONSE" ]; then
    log_check "PASS" "Roteamento / está funcionando (frontend respondeu)"
    
    # Verificar se resposta parece ser do frontend
    if echo "$ROOT_RESPONSE" | grep -qiE "(html|<!DOCTYPE|next|react|script)"; then
        log_check "PASS" "Resposta parece ser do frontend (contém HTML/Next.js)"
    else
        log_check "WARN" "Resposta pode não ser do frontend esperado"
    fi
else
    log_check "FAIL" "Roteamento / não está funcionando (sem resposta)"
fi

# 4.3 Verificar se /health roteia para backend
log_check "INFO" "Verificando roteamento /health → backend..."
HEALTH_RESPONSE=$(curl -s --max-time 10 "http://$VM_IP/health" 2>/dev/null || echo "")
if [ -n "$HEALTH_RESPONSE" ]; then
    log_check "PASS" "Roteamento /health está funcionando (backend respondeu)"
else
    log_check "WARN" "Roteamento /health pode não estar funcionando"
fi

echo ""

# ============================================
# PARTE 5: ANÁLISE DE CONTEÚDO
# ============================================
log_section "📄 PARTE 5: ANÁLISE DE CONTEÚDO"

# 5.1 Analisar resposta do frontend
if [ -n "$ROOT_RESPONSE" ]; then
    log_check "INFO" "Analisando resposta do frontend..."
    
    # Verificar se tem NEXT_PUBLIC_API_URL embutido
    if echo "$ROOT_RESPONSE" | grep -qi "NEXT_PUBLIC_API_URL\|api/v1"; then
        log_check "PASS" "Frontend parece estar configurado (contém referências à API)"
    else
        log_check "WARN" "Frontend pode não estar configurado corretamente (sem referências à API)"
    fi
    
    # Verificar tamanho da resposta
    RESPONSE_SIZE=$(echo "$ROOT_RESPONSE" | wc -c)
    if [ "$RESPONSE_SIZE" -gt 1000 ]; then
        log_check "PASS" "Frontend retornou resposta substancial (${RESPONSE_SIZE} bytes)"
    else
        log_check "WARN" "Frontend retornou resposta pequena (${RESPONSE_SIZE} bytes - pode estar com erro)"
    fi
fi

# 5.2 Analisar resposta do backend
if [ -n "$API_HEALTH_RESPONSE" ]; then
    log_check "INFO" "Analisando resposta do backend..."
    
    # Verificar formato JSON
    if echo "$API_HEALTH_RESPONSE" | grep -qE "^\s*\{.*\}\s*$" || echo "$API_HEALTH_RESPONSE" | grep -qE "\"status\"|\"ok\"|\"healthy\""; then
        log_check "PASS" "Backend retornou JSON válido"
    else
        log_check "WARN" "Backend pode não estar retornando JSON válido"
    fi
fi

echo ""

# ============================================
# PARTE 6: RESUMO E RECOMENDAÇÕES
# ============================================
log_section "📊 RESUMO FINAL"

echo "=========================================="
echo "📈 ESTATÍSTICAS"
echo "=========================================="
echo ""
echo "Total de verificações: $TOTAL_CHECKS"
echo -e "${GREEN}[OK] Passou: $PASSED_CHECKS${NC}"
echo -e "${YELLOW}[WARNING] Avisos: $WARNING_CHECKS${NC}"
echo -e "${RED}[ERROR] Falhou: $FAILED_CHECKS${NC}"
echo ""

# Calcular porcentagem
if [ $TOTAL_CHECKS -gt 0 ]; then
    PASS_PERCENT=$((PASSED_CHECKS * 100 / TOTAL_CHECKS))
    echo "Taxa de sucesso: ${PASS_PERCENT}%"
    echo ""
fi

# Conclusão
echo "=========================================="
echo "🎯 CONCLUSÃO"
echo "=========================================="
echo ""

if [ $FAILED_CHECKS -eq 0 ] && [ $WARNING_CHECKS -eq 0 ]; then
    echo -e "${GREEN}[OK] TUDO FUNCIONANDO PERFEITAMENTE!${NC}"
    echo ""
    echo "Frontend e Backend estão conectados e funcionando corretamente."
    echo "Todas as verificações passaram sem erros ou avisos."
elif [ $FAILED_CHECKS -eq 0 ]; then
    echo -e "${YELLOW}[WARNING] FUNCIONANDO COM AVISOS${NC}"
    echo ""
    echo "Frontend e Backend estão conectados e funcionando, mas há alguns avisos."
    echo "Recomenda-se verificar os pontos mencionados acima."
else
    echo -e "${RED}[ERROR] PROBLEMAS ENCONTRADOS${NC}"
    echo ""
    echo "Há problemas que precisam ser corrigidos."
    echo "Verifique os erros acima e corrija antes de continuar."
fi

echo ""
echo "=========================================="
echo " RECOMENDAÇÕES"
echo "=========================================="
echo ""

if [ $FAILED_CHECKS -gt 0 ] || [ $WARNING_CHECKS -gt 0 ]; then
    echo "1. Verificar containers na VM:"
    echo "   ssh azureuser@$VM_IP"
    echo "   sudo docker compose ps"
    echo ""
    echo "2. Verificar logs:"
    echo "   sudo docker compose logs backend --tail=50"
    echo "   sudo docker compose logs frontend --tail=50"
    echo "   sudo docker compose logs proxy --tail=50"
    echo ""
    echo "3. Verificar configuração .env:"
    echo "   cat ~/projeto/sky-poc-infra/.env | grep NEXT_PUBLIC_API_URL"
    echo ""
    echo "4. Verificar Nginx:"
    echo "   sudo docker exec ai_saas_proxy nginx -t"
    echo "   sudo docker exec ai_saas_proxy cat /etc/nginx/conf.d/default.conf | grep -A 5 'location /api'"
    echo ""
    echo "5. Testar conectividade interna:"
    echo "   sudo docker exec ai_saas_frontend_prod curl -s http://backend:8000/health"
    echo "   sudo docker exec ai_saas_backend_prod curl -s http://frontend:3000"
fi

echo ""
echo "=========================================="
echo "[OK] Verificação concluída"
echo "=========================================="
echo ""

if [ $FAILED_CHECKS -gt 0 ]; then
    exit 1
else
    exit 0
fi

