#!/bin/bash
# Script simples para corrigir NEXT_PUBLIC_API_URL na VM
# Pode ser copiado e executado diretamente na VM

set -eu

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}[OK] $1${NC}"; }
log_error() { echo -e "${RED}[ERROR] $1${NC}"; }

echo "=========================================="
echo " Correção Rápida: NEXT_PUBLIC_API_URL"
echo "=========================================="
echo ""

# Encontrar diretório do projeto
PROJECT_DIR=""
if [ -d ~/projeto/sky-poc-infra ]; then
    PROJECT_DIR=~/projeto/sky-poc-infra
elif [ -d ~/projeto/poc-deploy ]; then
    PROJECT_DIR=~/projeto/poc-deploy
else
    log_error "Diretório do projeto não encontrado"
    exit 1
fi

cd "$PROJECT_DIR"
log_success "Diretório: $PROJECT_DIR"

ENV_FILE=".env"

# Verificar se .env existe
if [ ! -f "$ENV_FILE" ]; then
    log_error "Arquivo .env não encontrado"
    if [ -f env.example ]; then
        log_info "Criando .env a partir de env.example..."
        cp env.example .env
        chmod 600 .env
    else
        log_error "env.example também não encontrado"
        exit 1
    fi
fi

# Obter IP da VM
log_info "Obtendo IP da VM..."
VM_IP=$(curl -s -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | grep -oP '"publicIpAddress":"\K[^"]+' | head -1 || echo "")

if [ -z "$VM_IP" ]; then
    VM_IP=$(curl -s http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01 -H "Metadata:true" 2>/dev/null || echo "")
fi

if [ -n "$VM_IP" ]; then
    log_success "IP da VM: $VM_IP"
else
    log_warning "Não foi possível obter IP automaticamente"
    VM_IP="20.86.142.1"  # IP conhecido
    log_info "Usando IP conhecido: $VM_IP"
fi

# Verificar valor atual
CURRENT_URL=$(grep "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "")

log_info "Valor atual: ${CURRENT_URL:-'não configurado'}"

# Detectar problemas
NEEDS_FIX=false
FIX_REASON=""

if [ -z "$CURRENT_URL" ]; then
    NEEDS_FIX=true
    FIX_REASON="não configurado"
elif echo "$CURRENT_URL" | grep -qE "localhost:8000|127\.0\.0\.1:8000"; then
    NEEDS_FIX=true
    FIX_REASON="usa localhost:8000 (não funciona em containers)"
fi

# Aplicar correção
if [ "$NEEDS_FIX" = "true" ]; then
    log_info "Aplicando correção..."
    
    # Preferir path relativo (melhor prática)
    NEW_URL="/api/v1"
    
    if grep -q "^NEXT_PUBLIC_API_URL=" "$ENV_FILE"; then
        sed -i "s|^NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=${NEW_URL}|" "$ENV_FILE"
    else
        echo "NEXT_PUBLIC_API_URL=${NEW_URL}" >> "$ENV_FILE"
    fi
    
    log_success "Corrigido para: $NEW_URL ($FIX_REASON)"
    log_info "Recomendação: usar path relativo /api/v1 (funciona através do Nginx)"
else
    if echo "$CURRENT_URL" | grep -qE "^/api/v1$"; then
        log_success "Já está usando path relativo (correto!): $CURRENT_URL"
    elif echo "$CURRENT_URL" | grep -q "$VM_IP"; then
        log_success "Já está configurado com IP correto: $CURRENT_URL"
    else
        log_warning "Valor atual: $CURRENT_URL (verifique se está correto)"
    fi
fi

# Verificar CORS também
log_info ""
log_info "Verificando CORS_ORIGINS..."
if grep -q "^CORS_ORIGINS=" "$ENV_FILE"; then
    CORS_CURRENT=$(grep "^CORS_ORIGINS=" "$ENV_FILE" | cut -d'=' -f2-)
    if ! echo "$CORS_CURRENT" | grep -q "$VM_IP"; then
        log_warning "CORS_ORIGINS pode não incluir o IP da VM"
        log_info "Atual: $CORS_CURRENT"
        log_info "Recomendado: http://${VM_IP},http://${VM_IP}:3000,http://localhost:3000"
    else
        log_success "CORS_ORIGINS parece correto"
    fi
fi

echo ""
echo "=========================================="
echo "📋 Resumo"
echo "=========================================="
echo ""
echo "NEXT_PUBLIC_API_URL: $(grep "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" | cut -d'=' -f2- || echo 'não encontrado')"
echo ""

if [ "$NEEDS_FIX" = "true" ]; then
    log_info "Próximos passos:"
    echo "  1. Reiniciar frontend: docker compose restart frontend"
    echo "  2. Verificar se o erro foi resolvido"
    echo ""
fi

