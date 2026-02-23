#!/bin/bash
# Script completo para verificar se conseguimos entrar e logar
# Executa todos os testes necessários e gera relatório
# Uso: ./scripts/verify-login-complete.sh [VM_IP]

set -eu

VM_IP="${1:-}"
TIMEOUT="${2:-15}"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

ERRORS=0
WARNINGS=0
CHECKS_PASSED=0

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
    ((CHECKS_PASSED++))
}

log_warning() {
    echo -e "${YELLOW}[WARNING] ${NC} $1"
    ((WARNINGS++))
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    ((ERRORS++))
}

log_info() {
    echo -e "${BLUE}ℹ️  ${NC} $1"
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

# Obter IP se não fornecido
if [ -z "$VM_IP" ]; then
    log_info "Tentando obter IP da VM automaticamente..."
    
    # Tentar via Terraform
    if [ -d "infra/azure" ]; then
        cd infra/azure
        VM_IP=$(terraform output -raw vm_public_ip 2>/dev/null || echo "")
        cd ../..
    fi
    
    # Tentar via Azure CLI
    if [ -z "$VM_IP" ]; then
        VM_IP=$(az vm list-ip-addresses --query "[?contains(name, 'poc-sky') || contains(name, 'ai-saas')].virtualMachine.network.publicIpAddresses[0].ipAddress" -o tsv 2>/dev/null | head -1 || echo "")
    fi
    
    if [ -z "$VM_IP" ]; then
        log_error "IP da VM não fornecido e não foi possível obter automaticamente"
        echo ""
        echo "Forneça o IP manualmente:"
        echo "  $0 <VM_IP>"
        echo ""
        echo "Ou obtenha o IP via:"
        echo "  1. GitHub Actions → Terraform Apply → vm_public_ip"
        echo "  2. Azure Portal → Resource Groups → Public IP addresses"
        exit 1
    fi
fi

echo "=========================================="
echo -e "${CYAN}🔍 VERIFICAÇÃO COMPLETA - ENTRAR E LOGAR${NC}"
echo "=========================================="
echo ""
echo "VM IP: $VM_IP"
echo "Timeout: ${TIMEOUT}s"
echo ""

# ============================================
# TESTE 1: Conectividade Básica
# ============================================
echo "=========================================="
echo "1.  Conectividade Básica"
echo "=========================================="
echo ""

log_info "Testando porta 80..."
if timeout 5 bash -c "echo > /dev/tcp/$VM_IP/80" 2>/dev/null; then
    log_success "Porta 80 acessível"
else
    log_error "Porta 80 não acessível"
fi

# ============================================
# TESTE 2: Frontend Acessível
# ============================================
echo ""
echo "=========================================="
echo "2.  Frontend Acessível"
echo "=========================================="
echo ""

log_info "Testando frontend (página inicial)..."
if test_http "http://$VM_IP/" "200" "$TIMEOUT"; then
    log_success "Frontend responde (HTTP 200)"
    
    # Verificar conteúdo
    FRONTEND_RESPONSE=$(curl -s --max-time "$TIMEOUT" "http://$VM_IP/" 2>/dev/null || echo "")
    if echo "$FRONTEND_RESPONSE" | grep -qiE "(html|<!DOCTYPE|next|react)"; then
        log_success "Frontend retorna HTML válido"
    else
        log_warning "Frontend pode não estar retornando HTML válido"
    fi
    
    # Verificar se tem referências à API
    if echo "$FRONTEND_RESPONSE" | grep -qi "NEXT_PUBLIC_API_URL\|api/v1"; then
        log_success "Frontend parece estar configurado para chamar API"
    else
        log_warning "Frontend pode não estar configurado corretamente"
    fi
elif [ $? -eq 2 ]; then
    log_error "Frontend não responde (timeout/conexão recusada)"
else
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "http://$VM_IP/" 2>/dev/null || echo "000")
    log_error "Frontend retornou HTTP $HTTP_CODE (esperado 200)"
fi

# ============================================
# TESTE 3: Backend Health Check
# ============================================
echo ""
echo "=========================================="
echo "3.  Backend Health Check"
echo "=========================================="
echo ""

log_info "Testando backend health check..."
if test_http "http://$VM_IP/health" "200" "$TIMEOUT"; then
    log_success "Backend Health Check responde (HTTP 200)"
    HEALTH_RESPONSE=$(curl -s --max-time "$TIMEOUT" "http://$VM_IP/health" 2>/dev/null || echo "")
    if [ -n "$HEALTH_RESPONSE" ]; then
        log_success "Backend retornou resposta: $(echo "$HEALTH_RESPONSE" | head -c 50)"
    fi
else
    log_error "Backend Health Check não responde"
fi

log_info "Testando API health check..."
if test_http "http://$VM_IP/api/v1/health" "200" "$TIMEOUT"; then
    log_success "API Health Check responde (HTTP 200)"
else
    log_error "API Health Check não responde"
fi

# ============================================
# TESTE 4: API Acessível
# ============================================
echo ""
echo "=========================================="
echo "4.  API Backend Acessível"
echo "=========================================="
echo ""

log_info "Testando API base..."
if test_http "http://$VM_IP/api/v1/" "200" "$TIMEOUT"; then
    log_success "API Base responde (HTTP 200)"
elif test_http "http://$VM_IP/api/v1/" "404" "$TIMEOUT"; then
    log_success "API Base responde (HTTP 404 - OK se não tiver rota raiz)"
elif test_http "http://$VM_IP/api/v1/" "405" "$TIMEOUT"; then
    log_success "API Base responde (HTTP 405 - OK se método não permitido)"
else
    log_error "API Base não responde"
fi

# ============================================
# TESTE 5: CORS Configurado
# ============================================
echo ""
echo "=========================================="
echo "5.  CORS Configurado"
echo "=========================================="
echo ""

log_info "Testando CORS..."
CORS_HEADERS=$(curl -s -I --max-time "$TIMEOUT" \
    -H "Origin: http://$VM_IP" \
    "http://$VM_IP/api/v1/health" 2>/dev/null || echo "")

if echo "$CORS_HEADERS" | grep -qi "Access-Control-Allow-Origin"; then
    log_success "CORS está configurado"
    CORS_ORIGIN=$(echo "$CORS_HEADERS" | grep -i "Access-Control-Allow-Origin" | head -1)
    echo "   $CORS_ORIGIN"
    
    if echo "$CORS_ORIGIN" | grep -q "http://$VM_IP"; then
        log_success "CORS permite origem do IP da VM"
    elif echo "$CORS_ORIGIN" | grep -q "*"; then
        log_warning "CORS permite qualquer origem (*) - risco de segurança"
    else
        log_warning "CORS pode não permitir origem do IP da VM"
    fi
else
    log_error "CORS não está configurado (pode bloquear requisições)"
fi

# ============================================
# TESTE 6: Roteamento Nginx
# ============================================
echo ""
echo "=========================================="
echo "6.  Roteamento Nginx"
echo "=========================================="
echo ""

log_info "Verificando roteamento /api/v1/ → backend..."
API_RESPONSE=$(curl -s --max-time "$TIMEOUT" "http://$VM_IP/api/v1/health" 2>/dev/null || echo "")
if [ -n "$API_RESPONSE" ]; then
    log_success "Roteamento /api/v1/ está funcionando"
else
    log_error "Roteamento /api/v1/ não está funcionando"
fi

log_info "Verificando roteamento / → frontend..."
ROOT_RESPONSE=$(curl -s --max-time "$TIMEOUT" "http://$VM_IP/" 2>/dev/null || echo "")
if echo "$ROOT_RESPONSE" | grep -qiE "(html|next|react)"; then
    log_success "Roteamento / está funcionando"
else
    log_error "Roteamento / não está funcionando"
fi

# ============================================
# RESUMO FINAL
# ============================================
echo ""
echo "=========================================="
echo "📊 RESUMO FINAL"
echo "=========================================="
echo ""
echo "Verificações passadas: $CHECKS_PASSED"
echo "Avisos: $WARNINGS"
echo "Erros: $ERRORS"
echo ""

# Conclusão
echo "=========================================="
echo "🎯 CONCLUSÃO"
echo "=========================================="
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}[OK] SIM, VOCÊ DEVE CONSEGUIR ENTRAR E LOGAR!${NC}"
    echo ""
    echo "Todos os testes passaram:"
    echo "  [OK] Frontend está acessível"
    echo "  [OK] Backend está respondendo"
    echo "  [OK] API está acessível"
    echo "  [OK] CORS está configurado"
    echo "  [OK] Roteamento está funcionando"
    echo ""
    echo "Teste manualmente:"
    echo "  1. Abra: http://$VM_IP/"
    echo "  2. Tente fazer login"
    echo "  3. Verifique o console do browser (F12) se houver erros"
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}[WARNING] PROVAVELMENTE SIM, MAS COM AVISOS${NC}"
    echo ""
    echo "A maioria dos testes passou, mas há avisos:"
    echo "  - Verifique os pontos mencionados acima"
    echo ""
    echo "Teste manualmente:"
    echo "  1. Abra: http://$VM_IP/"
    echo "  2. Tente fazer login"
    echo "  3. Verifique o console do browser (F12) para erros"
else
    echo -e "${RED}[ERROR] NÃO, HÁ PROBLEMAS QUE IMPEDEM O ACESSO${NC}"
    echo ""
    echo "Há erros que precisam ser corrigidos:"
    echo "  - Verifique os erros acima"
    echo ""
    echo "Possíveis problemas:"
    echo "  - Containers não estão rodando"
    echo "  - Nginx não está configurado corretamente"
    echo "  - Backend não está respondendo"
    echo "  - CORS não está configurado"
    echo ""
    echo "Verifique na VM:"
    echo "  ssh azureuser@$VM_IP"
    echo "  sudo docker compose ps"
    echo "  sudo docker compose logs backend --tail=50"
    echo "  sudo docker compose logs frontend --tail=50"
fi

echo ""
echo "=========================================="
echo "[OK] Verificação concluída"
echo "=========================================="
echo ""

if [ $ERRORS -gt 0 ]; then
    exit 1
else
    exit 0
fi

