#!/bin/bash
# Script de Smoke Tests - Testes básicos após deploy
# Valida se a aplicação está funcionando corretamente após o deploy
# Uso: ./scripts/smoke-tests.sh <VM_IP> [TIMEOUT]

set -eu

VM_IP="${1:-}"
TIMEOUT="${2:-30}"

if [ -z "$VM_IP" ]; then
    echo "❌ ERRO: IP da VM não fornecido"
    echo "Uso: $0 <VM_IP> [TIMEOUT]"
    exit 1
fi

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Função para log de erro
log_error() {
    echo -e "${RED}❌ ERRO:${NC} $1" >&2
    ((ERRORS++))
}

# Função para log de aviso
log_warning() {
    echo -e "${YELLOW}⚠️  AVISO:${NC} $1"
    ((WARNINGS++))
}

# Função para log de sucesso
log_success() {
    echo -e "${GREEN}✅${NC} $1"
}

# Função para testar endpoint HTTP
test_endpoint() {
    local url="$1"
    local expected_status="${2:-200}"
    local description="${3:-$url}"
    local timeout="${4:-10}"
    
    echo -n "Testando $description... "
    
    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$timeout" --connect-timeout 5 "$url" 2>/dev/null || echo "000")
    
    if [ "$response" = "$expected_status" ]; then
        log_success "$description (HTTP $response)"
        return 0
    elif [ "$response" = "000" ]; then
        log_error "$description (timeout/conexão recusada)"
        return 1
    else
        log_error "$description (esperado HTTP $expected_status, recebido HTTP $response)"
        return 1
    fi
}

# Função para testar endpoint com validação de conteúdo
test_endpoint_with_content() {
    local url="$1"
    local expected_content="$2"
    local description="${3:-$url}"
    local timeout="${4:-10}"
    
    echo -n "Testando $description... "
    
    response=$(curl -s --max-time "$timeout" --connect-timeout 5 "$url" 2>/dev/null || echo "")
    
    if [ -z "$response" ]; then
        log_error "$description (sem resposta)"
        return 1
    fi
    
    if echo "$response" | grep -q "$expected_content"; then
        log_success "$description (conteúdo válido)"
        return 0
    else
        log_error "$description (conteúdo inválido - esperado: $expected_content)"
        return 1
    fi
}

echo "=========================================="
echo "🧪 Smoke Tests - Validação Pós-Deploy"
echo "=========================================="
echo ""
echo "VM IP: $VM_IP"
echo "Timeout: ${TIMEOUT}s"
echo ""

# Aguardar um pouco para garantir que serviços iniciaram
echo "Aguardando serviços iniciarem (5s)..."
sleep 5

echo ""
echo "=========================================="
echo "📡 Testando Conectividade Básica"
echo "=========================================="
echo ""

# Teste 1: Conectividade básica (porta 80)
if timeout 5 bash -c "echo > /dev/tcp/$VM_IP/80" 2>/dev/null; then
    log_success "Porta 80 acessível"
else
    log_error "Porta 80 não acessível"
fi

echo ""
echo "=========================================="
echo "🏥 Testando Health Checks"
echo "=========================================="
echo ""

# Teste 2: Health check do backend
test_endpoint "http://$VM_IP/health" "200" "Health Check do Backend" "$TIMEOUT"

# Teste 3: Health check com validação de conteúdo (se disponível)
if test_endpoint "http://$VM_IP/health" "200" "Health Check (HTTP)" "$TIMEOUT"; then
    # Tentar validar conteúdo se endpoint retornar JSON
    health_response=$(curl -s --max-time 10 "http://$VM_IP/health" 2>/dev/null || echo "")
    if echo "$health_response" | grep -qE "(status|healthy|ok)" || [ -n "$health_response" ]; then
        log_success "Health Check retornou resposta válida"
    else
        log_warning "Health Check retornou resposta vazia ou inválida"
    fi
fi

echo ""
echo "=========================================="
echo "🌐 Testando Frontend"
echo "=========================================="
echo ""

# Teste 4: Frontend acessível
test_endpoint "http://$VM_IP/" "200" "Frontend (página inicial)" "$TIMEOUT"

# Teste 5: Frontend retorna HTML
frontend_response=$(curl -s --max-time 10 "http://$VM_IP/" 2>/dev/null || echo "")
if echo "$frontend_response" | grep -qiE "(html|<!DOCTYPE|next)" >/dev/null 2>&1; then
    log_success "Frontend retorna HTML válido"
else
    log_warning "Frontend pode não estar retornando HTML válido"
fi

echo ""
echo "=========================================="
echo "🔌 Testando API Backend"
echo "=========================================="
echo ""

# Teste 6: API endpoint base
test_endpoint "http://$VM_IP/api/v1/" "200" "API Base (/api/v1/)" "$TIMEOUT" || \
test_endpoint "http://$VM_IP/api/v1/" "404" "API Base (/api/v1/ - 404 OK se não tiver rota raiz)" "$TIMEOUT" || \
test_endpoint "http://$VM_IP/api/v1/" "405" "API Base (/api/v1/ - 405 OK se método não permitido)" "$TIMEOUT"

# Teste 7: API health endpoint (se disponível)
test_endpoint "http://$VM_IP/api/v1/health" "200" "API Health Check" "$TIMEOUT" || \
log_warning "API Health Check não disponível em /api/v1/health"

# Teste 8: CORS headers (OPTIONS request)
echo -n "Testando CORS (OPTIONS)... "
cors_response=$(curl -s -o /dev/null -w "%{http_code}" -X OPTIONS \
    -H "Origin: http://localhost:3000" \
    -H "Access-Control-Request-Method: GET" \
    --max-time 10 \
    "http://$VM_IP/api/v1/health" 2>/dev/null || echo "000")

if [ "$cors_response" = "204" ] || [ "$cors_response" = "200" ]; then
    log_success "CORS configurado (HTTP $cors_response)"
else
    log_warning "CORS pode não estar configurado corretamente (HTTP $cors_response)"
fi

echo ""
echo "=========================================="
echo "📊 Resumo dos Testes"
echo "=========================================="
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ Todos os testes passaram!${NC}"
    echo ""
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Testes concluídos com $WARNINGS aviso(s)${NC}"
    echo -e "${GREEN}✅ Nenhum erro crítico encontrado${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Testes falharam com $ERRORS erro(s) e $WARNINGS aviso(s)${NC}"
    echo ""
    echo "Verifique:"
    echo "  - Se os containers estão rodando"
    echo "  - Se o nginx/proxy está configurado corretamente"
    echo "  - Se as portas estão abertas no NSG"
    echo "  - Logs dos containers: docker compose logs"
    echo ""
    exit 1
fi

