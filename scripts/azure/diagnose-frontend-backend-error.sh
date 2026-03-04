#!/bin/bash
# Script DevOps: Diagnóstico específico para erro "Failed to load data. Please check if the backend is running on port 8000"
# Este script identifica e corrige problemas de comunicação entre frontend e backend

set -eu

PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
cd "$PROJECT_DIR" || {
    if [ -d ~/projeto/sky-poc-infra ]; then
        cd ~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        cd ~/projeto/poc-deploy
    else
        echo "❌ ERRO: Diretório do projeto não encontrado"
        exit 1
    fi
}

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }
log_section() { echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${CYAN}▶ $1${NC}"; echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }

ERRORS=0
WARNINGS=0
FIXES_APPLIED=0

echo "=========================================="
echo "🔍 DIAGNÓSTICO: Erro Frontend → Backend"
echo "=========================================="
echo "Erro: 'Failed to load data. Please check if the backend is running on port 8000'"
echo ""

# ============================================
# 1. VERIFICAR CONTAINERS
# ============================================
log_section "1. Verificando Containers Docker"

if ! command -v docker >/dev/null 2>&1; then
    log_error "Docker não está instalado"
    exit 1
fi

BACKEND_RUNNING=false
FRONTEND_RUNNING=false
PROXY_RUNNING=false

if docker ps --format "{{.Names}}" | grep -qE "backend|ai_saas_backend"; then
    BACKEND_RUNNING=true
    log_success "Backend container está rodando"
else
    log_error "Backend container NÃO está rodando"
    ERRORS=$((ERRORS + 1))
fi

if docker ps --format "{{.Names}}" | grep -qE "frontend|ai_saas_frontend"; then
    FRONTEND_RUNNING=true
    log_success "Frontend container está rodando"
else
    log_error "Frontend container NÃO está rodando"
    ERRORS=$((ERRORS + 1))
fi

if docker ps --format "{{.Names}}" | grep -qE "proxy|nginx|ai_saas_proxy"; then
    PROXY_RUNNING=true
    log_success "Proxy/Nginx container está rodando"
else
    log_warning "Proxy/Nginx container NÃO está rodando"
    WARNINGS=$((WARNINGS + 1))
fi

# ============================================
# 2. VERIFICAR NEXT_PUBLIC_API_URL
# ============================================
log_section "2. Verificando NEXT_PUBLIC_API_URL"

ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    log_error "Arquivo .env não encontrado"
    ERRORS=$((ERRORS + 1))
else
    log_success "Arquivo .env encontrado"
    
    if grep -q "^NEXT_PUBLIC_API_URL=" "$ENV_FILE"; then
        CURRENT_URL=$(grep "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
        log_info "Valor atual: $CURRENT_URL"
        
        # Verificar problemas
        if echo "$CURRENT_URL" | grep -qE "localhost:8000|127\.0\.0\.1:8000"; then
            log_error "PROBLEMA CRÍTICO: URL usa localhost:8000"
            log_error "  Isso NÃO funciona em containers Docker!"
            log_error "  O frontend não consegue acessar o backend via localhost"
            ERRORS=$((ERRORS + 1))
            
            # Obter IP da VM
            VM_IP=$(curl -s -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | grep -oP '"publicIpAddress":"\K[^"]+' | head -1 || echo "")
            
            if [ -n "$VM_IP" ]; then
                log_info "Corrigindo para path relativo (recomendado)..."
                sed -i "s|^NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=/api/v1|" "$ENV_FILE"
                log_success "Corrigido para: /api/v1"
                FIXES_APPLIED=$((FIXES_APPLIED + 1))
            else
                log_warning "Não foi possível obter IP da VM automaticamente"
                log_info "Correção manual necessária:"
                log_info "  Opção 1 (recomendado): NEXT_PUBLIC_API_URL=/api/v1"
                log_info "  Opção 2: NEXT_PUBLIC_API_URL=http://<IP_DA_VM>/api/v1"
            fi
        elif echo "$CURRENT_URL" | grep -qE "^/api/v1$"; then
            log_success "URL está usando path relativo (correto!)"
        elif echo "$CURRENT_URL" | grep -qE "http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/api/v1"; then
            log_success "URL está usando IP completo: $CURRENT_URL"
            # Verificar se IP está correto
            VM_IP=$(curl -s -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | grep -oP '"publicIpAddress":"\K[^"]+' | head -1 || echo "")
            if [ -n "$VM_IP" ] && ! echo "$CURRENT_URL" | grep -q "$VM_IP"; then
                URL_IP=$(echo "$CURRENT_URL" | grep -oE "http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | sed 's|http://||')
                log_warning "IP pode estar desatualizado: $URL_IP (IP atual: $VM_IP)"
                WARNINGS=$((WARNINGS + 1))
            fi
        else
            log_warning "Formato de URL pode estar incorreto: $CURRENT_URL"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        log_error "NEXT_PUBLIC_API_URL não está configurado no .env"
        ERRORS=$((ERRORS + 1))
        
        # Tentar corrigir automaticamente
        VM_IP=$(curl -s -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | grep -oP '"publicIpAddress":"\K[^"]+' | head -1 || echo "")
        if [ -n "$VM_IP" ]; then
            log_info "Adicionando NEXT_PUBLIC_API_URL com path relativo..."
            echo "NEXT_PUBLIC_API_URL=/api/v1" >> "$ENV_FILE"
            log_success "Adicionado: NEXT_PUBLIC_API_URL=/api/v1"
            FIXES_APPLIED=$((FIXES_APPLIED + 1))
        else
            log_warning "Não foi possível adicionar automaticamente (IP não detectado)"
        fi
    fi
fi

# ============================================
# 3. VERIFICAR BACKEND ACESSÍVEL
# ============================================
log_section "3. Verificando Acessibilidade do Backend"

if [ "$BACKEND_RUNNING" = "true" ]; then
    # Teste 1: Backend localmente (dentro da rede Docker)
    if docker exec ai_saas_backend_prod python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=5)" 2>/dev/null; then
        log_success "Backend responde em localhost:8000 (dentro do container)"
    else
        log_warning "Backend não responde em localhost:8000 (dentro do container)"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    # Teste 2: Backend via Nginx (se proxy estiver rodando)
    if [ "$PROXY_RUNNING" = "true" ]; then
        if curl -s --max-time 5 http://localhost/api/v1/health > /dev/null 2>&1; then
            log_success "Backend acessível via Nginx (/api/v1/health)"
        else
            log_error "Backend NÃO acessível via Nginx"
            ERRORS=$((ERRORS + 1))
        fi
    fi
else
    log_error "Não é possível testar backend (container não está rodando)"
fi

# ============================================
# 4. VERIFICAR CORS
# ============================================
log_section "4. Verificando Configuração CORS"

if [ -f "$ENV_FILE" ] && grep -q "^CORS_ORIGINS=" "$ENV_FILE"; then
    CORS_ORIGINS=$(grep "^CORS_ORIGINS=" "$ENV_FILE" | cut -d'=' -f2-)
    log_info "CORS_ORIGINS: $CORS_ORIGINS"
    
    if echo "$CORS_ORIGINS" | grep -q "\*"; then
        log_error "CORS_ORIGINS contém '*' (vulnerabilidade de segurança!)"
        ERRORS=$((ERRORS + 1))
    else
        log_success "CORS_ORIGINS configurado (sem wildcard)"
    fi
else
    log_warning "CORS_ORIGINS não configurado"
    WARNINGS=$((WARNINGS + 1))
fi

# ============================================
# 5. VERIFICAR LOGS DO FRONTEND
# ============================================
log_section "5. Verificando Logs do Frontend"

if [ "$FRONTEND_RUNNING" = "true" ]; then
    FRONTEND_CONTAINER=$(docker ps --format "{{.Names}}" | grep -E "frontend|ai_saas_frontend" | head -1)
    if [ -n "$FRONTEND_CONTAINER" ]; then
        log_info "Últimas 20 linhas dos logs do frontend:"
        docker logs "$FRONTEND_CONTAINER" --tail=20 2>&1 | grep -iE "error|fail|8000|backend|api" || log_info "Nenhum erro relacionado encontrado nos logs recentes"
    fi
fi

# ============================================
# 6. RESUMO E RECOMENDAÇÕES
# ============================================
log_section "6. Resumo e Recomendações"

echo "Erros encontrados: $ERRORS"
echo "Avisos: $WARNINGS"
echo "Correções aplicadas: $FIXES_APPLIED"
echo ""

if [ $ERRORS -eq 0 ] && [ $FIXES_APPLIED -eq 0 ]; then
    log_success "Nenhum problema crítico encontrado!"
    echo ""
    echo "Se o erro persistir no frontend:"
    echo "  1. Verifique se o frontend foi reiniciado após mudanças no .env"
    echo "  2. Limpe o cache do navegador"
    echo "  3. Verifique o console do navegador para erros específicos"
    exit 0
elif [ $FIXES_APPLIED -gt 0 ]; then
    log_warning "Correções foram aplicadas. Próximos passos:"
    echo ""
    echo "1. Reiniciar o frontend para aplicar mudanças:"
    echo "   docker compose restart frontend"
    echo ""
    echo "2. Verificar se o erro foi resolvido no navegador"
    echo ""
    if [ $ERRORS -gt 0 ]; then
        exit 1
    else
        exit 0
    fi
else
    log_error "Problemas encontrados que precisam ser corrigidos manualmente"
    exit 1
fi

