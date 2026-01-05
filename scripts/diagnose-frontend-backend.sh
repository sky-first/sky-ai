#!/bin/bash
# Script de Diagnóstico DevOps - Frontend e Backend
# Verifica se estão conectados e funcionando corretamente
# Uso: ./scripts/diagnose-frontend-backend.sh [VM_IP]

set -eu

VM_IP="${1:-}"
TIMEOUT="${2:-10}"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0
CHECKS_PASSED=0

# Função para log
log_info() {
    echo -e "${BLUE}ℹ️  INFO:${NC} $1"
}

log_success() {
    echo -e "${GREEN}✅${NC} $1"
    ((CHECKS_PASSED++))
}

log_warning() {
    echo -e "${YELLOW}⚠️  AVISO:${NC} $1"
    ((WARNINGS++))
}

log_error() {
    echo -e "${RED}❌ ERRO:${NC} $1" >&2
    ((ERRORS++))
}

# Função para testar endpoint
test_endpoint() {
    local url="$1"
    local description="$2"
    local expected_status="${3:-200}"
    
    echo -n "  Testando $description... "
    
    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" --connect-timeout 5 "$url" 2>/dev/null || echo "000")
    
    if [ "$response" = "$expected_status" ] || [ "$response" = "000" ]; then
        if [ "$response" = "000" ]; then
            log_error "$description (sem resposta)"
            return 1
        else
            log_success "$description (HTTP $response)"
            return 0
        fi
    else
        log_warning "$description (esperado HTTP $expected_status, recebido HTTP $response)"
        return 0
    fi
}

echo "=========================================="
echo "🔍 DIAGNÓSTICO DEVOPS - Frontend/Backend"
echo "=========================================="
echo ""

if [ -z "$VM_IP" ]; then
    log_error "IP da VM não fornecido"
    echo "Uso: $0 <VM_IP> [TIMEOUT]"
    echo ""
    echo "Para obter o IP:"
    echo "  1. GitHub Actions → Terraform Apply → vm_public_ip"
    echo "  2. Azure Portal → Resource Groups → Public IP addresses"
    echo "  3. Azure CLI: az vm show -d -g <rg> -n <vm> --query publicIps"
    exit 1
fi

echo "VM IP: $VM_IP"
echo "Timeout: ${TIMEOUT}s"
echo ""

# ============================================
# 1. VERIFICAÇÃO DE CONECTIVIDADE BÁSICA
# ============================================
echo "=========================================="
echo "1️⃣  Conectividade Básica"
echo "=========================================="
echo ""

# Teste 1: Porta 80 acessível
echo -n "  Testando porta 80... "
if timeout 5 bash -c "echo > /dev/tcp/$VM_IP/80" 2>/dev/null; then
    log_success "Porta 80 acessível"
else
    log_error "Porta 80 não acessível"
fi

# Teste 2: Nginx respondendo
test_endpoint "http://$VM_IP/" "Nginx/Frontend (raiz)" "200"

echo ""

# ============================================
# 2. VERIFICAÇÃO DO BACKEND
# ============================================
echo "=========================================="
echo "2️⃣  Backend (FastAPI)"
echo "=========================================="
echo ""

# Teste 3: Health check do backend
test_endpoint "http://$VM_IP/health" "Backend Health Check (/health)" "200"

# Teste 4: API Health Check
test_endpoint "http://$VM_IP/api/v1/health" "API Health Check (/api/v1/health)" "200"

# Teste 5: API Base
test_endpoint "http://$VM_IP/api/v1/" "API Base (/api/v1/)" "200" || \
test_endpoint "http://$VM_IP/api/v1/" "API Base (/api/v1/)" "404" || \
test_endpoint "http://$VM_IP/api/v1/" "API Base (/api/v1/)" "405"

# Teste 6: Verificar conteúdo da resposta
echo -n "  Verificando resposta do backend... "
health_response=$(curl -s --max-time "$TIMEOUT" "http://$VM_IP/api/v1/health" 2>/dev/null || echo "")
if [ -n "$health_response" ]; then
    if echo "$health_response" | grep -qiE "(status|ok|healthy)" || echo "$health_response" | grep -q "{"; then
        log_success "Backend retornou resposta válida"
        echo "    Resposta: $(echo "$health_response" | head -c 100)"
    else
        log_warning "Backend retornou resposta inesperada: $(echo "$health_response" | head -c 50)"
    fi
else
    log_error "Backend não retornou resposta"
fi

echo ""

# ============================================
# 3. VERIFICAÇÃO DO FRONTEND
# ============================================
echo "=========================================="
echo "3️⃣  Frontend (Next.js)"
echo "=========================================="
echo ""

# Teste 7: Frontend acessível
test_endpoint "http://$VM_IP/" "Frontend (página inicial)" "200"

# Teste 8: Frontend retorna HTML
echo -n "  Verificando se frontend retorna HTML... "
frontend_response=$(curl -s --max-time "$TIMEOUT" "http://$VM_IP/" 2>/dev/null || echo "")
if echo "$frontend_response" | grep -qiE "(html|<!DOCTYPE|next|react)" >/dev/null 2>&1; then
    log_success "Frontend retorna HTML válido"
else
    log_warning "Frontend pode não estar retornando HTML válido"
fi

# Teste 9: Verificar se frontend está configurado corretamente
echo -n "  Verificando configuração do frontend... "
if echo "$frontend_response" | grep -qi "NEXT_PUBLIC_API_URL\|api/v1" >/dev/null 2>&1; then
    log_success "Frontend parece estar configurado"
else
    log_warning "Não foi possível verificar configuração do frontend na resposta"
fi

echo ""

# ============================================
# 4. VERIFICAÇÃO DE CORS
# ============================================
echo "=========================================="
echo "4️⃣  CORS (Cross-Origin Resource Sharing)"
echo "=========================================="
echo ""

# Teste 10: CORS Preflight (OPTIONS)
echo -n "  Testando CORS Preflight (OPTIONS)... "
cors_response=$(curl -s -o /dev/null -w "%{http_code}" -X OPTIONS \
    -H "Origin: http://$VM_IP" \
    -H "Access-Control-Request-Method: GET" \
    --max-time "$TIMEOUT" \
    "http://$VM_IP/api/v1/health" 2>/dev/null || echo "000")

if [ "$cors_response" = "204" ] || [ "$cors_response" = "200" ]; then
    log_success "CORS Preflight funcionando (HTTP $cors_response)"
else
    log_warning "CORS Preflight pode não estar funcionando (HTTP $cors_response)"
fi

# Teste 11: CORS Headers
echo -n "  Verificando headers CORS... "
cors_headers=$(curl -s -I --max-time "$TIMEOUT" \
    -H "Origin: http://$VM_IP" \
    "http://$VM_IP/api/v1/health" 2>/dev/null || echo "")

if echo "$cors_headers" | grep -qi "Access-Control-Allow-Origin"; then
    log_success "Headers CORS presentes"
    echo "    $(echo "$cors_headers" | grep -i "Access-Control-Allow-Origin" | head -1)"
else
    log_warning "Headers CORS podem não estar presentes"
fi

echo ""

# ============================================
# 5. VERIFICAÇÃO DE ROTEAMENTO NGINX
# ============================================
echo "=========================================="
echo "5️⃣  Roteamento Nginx"
echo "=========================================="
echo ""

# Teste 12: Verificar se /api/v1/ roteia para backend
echo -n "  Verificando roteamento /api/v1/ → backend... "
api_response=$(curl -s --max-time "$TIMEOUT" "http://$VM_IP/api/v1/health" 2>/dev/null || echo "")
if [ -n "$api_response" ]; then
    log_success "Roteamento /api/v1/ está funcionando"
else
    log_error "Roteamento /api/v1/ pode não estar funcionando"
fi

# Teste 13: Verificar se / roteia para frontend
echo -n "  Verificando roteamento / → frontend... "
root_response=$(curl -s --max-time "$TIMEOUT" "http://$VM_IP/" 2>/dev/null || echo "")
if echo "$root_response" | grep -qiE "(html|next|react)" >/dev/null 2>&1; then
    log_success "Roteamento / está funcionando"
else
    log_warning "Roteamento / pode não estar funcionando corretamente"
fi

echo ""

# ============================================
# 6. VERIFICAÇÃO DE CONFIGURAÇÃO
# ============================================
echo "=========================================="
echo "6️⃣  Configuração"
echo "=========================================="
echo ""

# Teste 14: Verificar se NEXT_PUBLIC_API_URL está correto
echo -n "  Verificando configuração NEXT_PUBLIC_API_URL... "
# Não podemos verificar diretamente, mas podemos inferir
if [ -n "$api_response" ] && [ -n "$root_response" ]; then
    log_success "Configuração parece estar correta (ambos respondem)"
else
    log_warning "Pode haver problema na configuração"
fi

echo ""

# ============================================
# 7. RESUMO E RECOMENDAÇÕES
# ============================================
echo "=========================================="
echo "📊 RESUMO DO DIAGNÓSTICO"
echo "=========================================="
echo ""

echo "✅ Verificações passadas: $CHECKS_PASSED"
echo "⚠️  Avisos: $WARNINGS"
echo "❌ Erros: $ERRORS"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ TUDO FUNCIONANDO PERFEITAMENTE!${NC}"
    echo ""
    echo "Frontend e Backend estão conectados e funcionando corretamente."
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  FUNCIONANDO COM AVISOS${NC}"
    echo ""
    echo "Frontend e Backend estão conectados, mas há alguns avisos."
    echo "Recomenda-se verificar os pontos mencionados acima."
else
    echo -e "${RED}❌ PROBLEMAS ENCONTRADOS${NC}"
    echo ""
    echo "Há problemas que precisam ser corrigidos."
    echo "Verifique os erros acima e corrija antes de continuar."
fi

echo ""
echo "=========================================="
echo "🔧 PRÓXIMOS PASSOS (se houver problemas)"
echo "=========================================="
echo ""

if [ $ERRORS -gt 0 ] || [ $WARNINGS -gt 0 ]; then
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
fi

echo ""
echo "=========================================="
echo "✅ Diagnóstico concluído"
echo "=========================================="
echo ""

if [ $ERRORS -gt 0 ]; then
    exit 1
else
    exit 0
fi

