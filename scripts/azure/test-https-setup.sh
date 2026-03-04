#!/bin/bash
# DEVOPS: Script de teste para validar configuração HTTPS
# Verifica se todos os componentes estão corretos antes do deploy

set -eu

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; ERRORS=$((ERRORS + 1)); }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; WARNINGS=$((WARNINGS + 1)); }

echo "=========================================="
echo "🧪 Teste de Validação - Configuração HTTPS"
echo "=========================================="
echo ""

# 1. Verificar scripts existem
log_info "1. Verificando scripts..."
SCRIPTS=(
    "scripts/azure/generate-self-signed-certs.sh"
    "scripts/azure/apply-nginx-config.sh"
    "scripts/azure/setup-https-vm-azure-cli.sh"
    "scripts/azure/setup-https-vm.sh"
    "scripts/azure/check-ssh-access.sh"
)

for script in "${SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        log_success "$script existe"
        if [ -x "$script" ]; then
            log_success "$script é executável"
        else
            log_warning "$script não é executável (chmod +x necessário)"
        fi
        # Verificar sintaxe
        if bash -n "$script" 2>/dev/null; then
            log_success "$script sintaxe OK"
        else
            log_error "$script tem erros de sintaxe"
        fi
    else
        log_error "$script não encontrado"
    fi
done

echo ""

# 2. Verificar arquivos de configuração Nginx
log_info "2. Verificando configurações Nginx..."
NGINX_CONFIGS=(
    "docker/nginx/nginx.conf"
    "docker/nginx/nginx.conf.http-only"
    "docker/nginx/nginx.conf.secure"
)

for config in "${NGINX_CONFIGS[@]}"; do
    if [ -f "$config" ]; then
        log_success "$config existe"
        # Verificar se tem DNS dinâmico (resolver)
        if grep -q "resolver 127.0.0.11" "$config"; then
            log_success "$config tem DNS dinâmico configurado"
        else
            log_warning "$config pode não ter DNS dinâmico (risco de 502 após recriação de containers)"
        fi
    else
        log_error "$config não encontrado"
    fi
done

echo ""

# 3. Verificar nginx.conf.secure tem HTTPS
log_info "3. Verificando nginx.conf.secure (HTTPS)..."
if [ -f "docker/nginx/nginx.conf.secure" ]; then
    if grep -q "listen 443 ssl" "docker/nginx/nginx.conf.secure"; then
        log_success "nginx.conf.secure tem porta 443 SSL"
    else
        log_error "nginx.conf.secure não tem porta 443 SSL"
    fi
    
    if grep -q "ssl_certificate" "docker/nginx/nginx.conf.secure"; then
        log_success "nginx.conf.secure tem ssl_certificate configurado"
    else
        log_error "nginx.conf.secure não tem ssl_certificate"
    fi
    
    if grep -q "return 301 https" "docker/nginx/nginx.conf.secure"; then
        log_success "nginx.conf.secure tem redirect HTTP->HTTPS"
    else
        log_warning "nginx.conf.secure pode não ter redirect HTTP->HTTPS"
    fi
fi

echo ""

# 4. Verificar docker-compose.yml
log_info "4. Verificando docker-compose.yml..."
if [ -f "docker-compose.yml" ]; then
    if grep -q "443:443" "docker-compose.yml"; then
        log_success "docker-compose.yml tem porta 443 mapeada"
    else
        log_error "docker-compose.yml não tem porta 443 mapeada"
    fi
    
    if grep -q "./certs:/etc/nginx/certs" "docker-compose.yml"; then
        log_success "docker-compose.yml tem volume de certificados configurado"
    else
        log_error "docker-compose.yml não tem volume de certificados"
    fi
    
    if grep -q "nginx.conf:/etc/nginx/conf.d/default.conf" "docker-compose.yml"; then
        log_success "docker-compose.yml tem nginx.conf mapeado"
    else
        log_error "docker-compose.yml não tem nginx.conf mapeado"
    fi
fi

echo ""

# 5. Verificar estrutura de diretórios
log_info "5. Verificando estrutura de diretórios..."
DIRS=(
    "docker/nginx"
    "scripts/azure"
)

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        log_success "$dir existe"
    else
        log_error "$dir não existe"
    fi
done

# Verificar se diretório certs pode ser criado
if mkdir -p certs 2>/dev/null; then
    log_success "Diretório certs pode ser criado"
    rmdir certs 2>/dev/null || true
else
    log_warning "Não foi possível criar diretório certs (pode ser problema de permissão)"
fi

echo ""

# 6. Verificar se openssl está disponível (para gerar certificados)
log_info "6. Verificando dependências..."
if command -v openssl >/dev/null 2>&1; then
    log_success "openssl está disponível"
else
    log_warning "openssl não está disponível localmente (será necessário na VM)"
fi

if command -v az >/dev/null 2>&1; then
    log_success "Azure CLI está disponível"
    if az account show >/dev/null 2>&1; then
        log_success "Azure CLI está logado"
    else
        log_warning "Azure CLI não está logado (az login necessário)"
    fi
else
    log_warning "Azure CLI não está disponível (necessário para setup-https-vm-azure-cli.sh)"
fi

echo ""

# 7. Resumo
echo "=========================================="
echo "📊 Resumo"
echo "=========================================="
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    log_success "Tudo OK! Nenhum erro ou aviso."
    exit 0
elif [ $ERRORS -eq 0 ]; then
    log_warning "$WARNINGS aviso(s) encontrado(s), mas nenhum erro crítico"
    exit 0
else
    log_error "$ERRORS erro(s) encontrado(s)"
    if [ $WARNINGS -gt 0 ]; then
        log_warning "$WARNINGS aviso(s) encontrado(s)"
    fi
    exit 1
fi

