#!/bin/bash
# Script DevOps: Valida que não há valores hardcoded perigosos nos repositórios
# Verifica se os repositórios estão seguindo as melhores práticas de configuração centralizada

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_error() {
    echo -e "${RED}❌ $1${NC}" >&2
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_info() {
    echo -e "ℹ️  $1"
}

echo "=========================================="
echo "🔍 Validação: Valores Hardcoded"
echo "=========================================="
echo ""

ERRORS=0
WARNINGS=0

# Verificar Frontend
echo "📦 Verificando Frontend (sky-poc-frontend)..."
FRONTEND_DIR="$PROJECT_ROOT/../sky-poc-frontend"

if [ -d "$FRONTEND_DIR" ]; then
    # Verificar client.ts
    if [ -f "$FRONTEND_DIR/src/lib/api/client.ts" ]; then
        if grep -qE 'http://localhost:8000/api/v1|http://127\\.0\\.0\\.1:8000/api/v1|http://YOUR_EC2_PUBLIC_IP:8000/api/v1' "$FRONTEND_DIR/src/lib/api/client.ts"; then
            log_error "Frontend client.ts contém URL absoluta hardcoded (deve usar NEXT_PUBLIC_API_URL=/api/v1)"
            ERRORS=$((ERRORS + 1))
        else
            log_success "Frontend client.ts não contém URL absoluta hardcoded"
        fi
    fi
    
    # Verificar login/page.tsx
    if [ -f "$FRONTEND_DIR/src/app/login/page.tsx" ]; then
        if grep -q 'localhost:8000' "$FRONTEND_DIR/src/app/login/page.tsx" && ! grep -q 'getApiBaseUrl' "$FRONTEND_DIR/src/app/login/page.tsx"; then
            log_warning "Frontend login/page.tsx pode ter 'localhost:8000' hardcoded (verifique se usa getApiBaseUrl)"
            WARNINGS=$((WARNINGS + 1))
        fi
    fi
    
    # Verificar env.example
    if [ -f "$FRONTEND_DIR/env.example" ]; then
        if grep -q 'YOUR_EC2_PUBLIC_IP' "$FRONTEND_DIR/env.example"; then
            log_warning "Frontend env.example contém placeholder 'YOUR_EC2_PUBLIC_IP' (deve ser removido ou documentado)"
            WARNINGS=$((WARNINGS + 1))
        fi
    fi
else
    log_warning "Diretório frontend não encontrado: $FRONTEND_DIR"
fi

echo ""

# Verificar Backend
echo "📦 Verificando Backend (sky-poc-backend)..."
BACKEND_DIR="$PROJECT_ROOT/../sky-poc-backend"

if [ -d "$BACKEND_DIR" ]; then
    if [ -f "$BACKEND_DIR/src/config/settings.py" ]; then
        # Verificar se tem validação de CORS_ORIGINS
        if grep -q 'validate_cors_origins' "$BACKEND_DIR/src/config/settings.py"; then
            log_success "Backend tem validação de CORS_ORIGINS"
        else
            log_warning "Backend não tem validação explícita de CORS_ORIGINS"
            WARNINGS=$((WARNINGS + 1))
        fi
        
        # Verificar se documenta que deve vir do sky-poc-infra
        if grep -q 'sky-poc-infra' "$BACKEND_DIR/src/config/settings.py"; then
            log_success "Backend documenta dependência do sky-poc-infra"
        else
            log_warning "Backend não documenta dependência do sky-poc-infra"
            WARNINGS=$((WARNINGS + 1))
        fi
    fi
else
    log_warning "Diretório backend não encontrado: $BACKEND_DIR"
fi

echo ""

# Verificar AI Service
echo "📦 Verificando AI Service (sky-poc-ai)..."
AI_DIR="$PROJECT_ROOT/../sky-poc-ai"

if [ -d "$AI_DIR" ]; then
    if [ -f "$AI_DIR/config/settings.py" ]; then
        # Verificar se documenta que deve vir do sky-poc-infra
        if grep -q 'sky-poc-infra' "$AI_DIR/config/settings.py"; then
            log_success "AI Service documenta dependência do sky-poc-infra"
        else
            log_warning "AI Service não documenta dependência do sky-poc-infra"
            WARNINGS=$((WARNINGS + 1))
        fi
    fi
else
    log_warning "Diretório AI não encontrado: $AI_DIR"
fi

echo ""

# Verificar Infraestrutura
echo "📦 Verificando Infraestrutura (sky-poc-infra)..."
INFRA_DIR="$PROJECT_ROOT"

if [ -f "$INFRA_DIR/env.example" ]; then
    if grep -q 'NEXT_PUBLIC_API_URL' "$INFRA_DIR/env.example" && grep -q '/api/v1' "$INFRA_DIR/env.example"; then
        log_success "Infraestrutura tem NEXT_PUBLIC_API_URL documentado com path relativo"
    else
        log_warning "Infraestrutura pode não ter NEXT_PUBLIC_API_URL documentado corretamente"
        WARNINGS=$((WARNINGS + 1))
    fi
fi

echo ""

# Resumo
echo "=========================================="
echo "📊 Resumo da Validação"
echo "=========================================="
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    log_success "Nenhum problema encontrado!"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    log_warning "Encontrados $WARNINGS avisos (não críticos)"
    exit 0
else
    log_error "Encontrados $ERRORS erros e $WARNINGS avisos"
    echo ""
    echo "💡 Para corrigir:"
    echo "   1. Remova valores hardcoded de localhost:8000"
    echo "   2. Use apenas variáveis de ambiente do .env do sky-poc-infra"
    echo "   3. Adicione validação para configurações críticas"
    echo "   4. Documente dependências do sky-poc-infra"
    exit 1
fi

