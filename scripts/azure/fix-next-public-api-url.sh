#!/bin/bash
# Script DevOps: Corrige NEXT_PUBLIC_API_URL no .env
# Garante que o frontend consegue acessar o backend corretamente
# Uso: ./scripts/azure/fix-next-public-api-url.sh [PROJECT_DIR] [PREFER_RELATIVE_PATH]

set -eu

PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
PREFER_RELATIVE="${2:-true}"  # true = preferir path relativo, false = usar IP completo

cd "$PROJECT_DIR" || {
    if [ -d ~/projeto/sky-poc-infra ]; then
        cd ~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        cd ~/projeto/poc-deploy
    else
        echo "[ERROR] ERRO: Diretório do projeto não encontrado"
        exit 1
    fi
}

ENV_FILE=".env"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

echo "=========================================="
echo " Correção de NEXT_PUBLIC_API_URL"
echo "=========================================="
echo ""

# Verificar se .env existe
if [ ! -f "$ENV_FILE" ]; then
    log_error "Arquivo .env não encontrado em: $(pwd)"
    echo "   Execute primeiro: cp env.example .env"
    exit 1
fi

# Obter IP público da VM
log_info "Obtendo IP público da VM..."
VM_IP=$(curl -s -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | grep -oP '"publicIpAddress":"\K[^"]+' | head -1 || echo "")

if [ -z "$VM_IP" ]; then
    VM_IP=$(curl -s http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01 -H "Metadata:true" 2>/dev/null || echo "")
fi

# Verificar valor atual
CURRENT_URL=$(grep "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "")

log_info "Valor atual: ${CURRENT_URL:-'não configurado'}"

# Detectar problemas
PROBLEMS=0

# Problema 1: localhost:8000 (não funciona em containers)
if echo "$CURRENT_URL" | grep -qE "localhost:8000|127\.0\.0\.1:8000"; then
    log_error "Problema detectado: URL usa localhost:8000 (não funciona em containers Docker)"
    PROBLEMS=$((PROBLEMS + 1))
fi

# Problema 2: IP antigo/incorreto
if [ -n "$VM_IP" ] && echo "$CURRENT_URL" | grep -qE "http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" && ! echo "$CURRENT_URL" | grep -q "$VM_IP"; then
    OLD_IP=$(echo "$CURRENT_URL" | grep -oE "http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | sed 's|http://||')
    log_warning "IP detectado ($OLD_IP) pode estar desatualizado (IP atual: $VM_IP)"
    PROBLEMS=$((PROBLEMS + 1))
fi

# Problema 3: Não configurado
if [ -z "$CURRENT_URL" ]; then
    log_error "NEXT_PUBLIC_API_URL não está configurado"
    PROBLEMS=$((PROBLEMS + 1))
fi

# Determinar valor correto
if [ "$PREFER_RELATIVE" = "true" ]; then
    # Preferir path relativo (melhor prática)
    CORRECT_URL="/api/v1"
    log_info "Usando path relativo (recomendado): $CORRECT_URL"
else
    # Usar IP completo
    if [ -z "$VM_IP" ]; then
        log_error "Não foi possível obter IP da VM e path relativo não foi escolhido"
        exit 1
    fi
    CORRECT_URL="http://${VM_IP}/api/v1"
    log_info "Usando URL completa: $CORRECT_URL"
fi

# Aplicar correção se necessário
NEEDS_FIX=false

if [ -z "$CURRENT_URL" ]; then
    NEEDS_FIX=true
elif echo "$CURRENT_URL" | grep -qE "localhost:8000|127\.0\.0\.1:8000"; then
    NEEDS_FIX=true
elif [ "$PREFER_RELATIVE" = "true" ] && [ "$CURRENT_URL" != "/api/v1" ]; then
    NEEDS_FIX=true
elif [ "$PREFER_RELATIVE" = "false" ] && [ -n "$VM_IP" ] && [ "$CURRENT_URL" != "http://${VM_IP}/api/v1" ]; then
    NEEDS_FIX=true
fi

if [ "$NEEDS_FIX" = "true" ]; then
    log_info "Aplicando correção..."
    
    if grep -q "^NEXT_PUBLIC_API_URL=" "$ENV_FILE"; then
        # Atualizar existente
        sed -i "s|^NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=${CORRECT_URL}|" "$ENV_FILE"
    else
        # Adicionar novo
        echo "NEXT_PUBLIC_API_URL=${CORRECT_URL}" >> "$ENV_FILE"
    fi
    
    log_success "NEXT_PUBLIC_API_URL atualizado para: $CORRECT_URL"
    
    # Verificar se frontend precisa ser reiniciado
    if command -v docker >/dev/null 2>&1; then
        if docker ps --format "{{.Names}}" | grep -q "frontend\|ai_saas_frontend"; then
            log_info "Frontend container detectado - será necessário reiniciar"
            log_info "Execute: docker compose restart frontend"
        fi
    fi
else
    log_success "NEXT_PUBLIC_API_URL já está correto: $CURRENT_URL"
fi

echo ""
echo "=========================================="
echo "📋 Resumo"
echo "=========================================="
echo ""
echo "Valor configurado: $(grep "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" | cut -d'=' -f2- || echo 'não encontrado')"
echo "IP da VM: ${VM_IP:-'não detectado'}"
echo "Problemas encontrados: $PROBLEMS"
echo ""

if [ "$PROBLEMS" -eq 0 ] && [ "$NEEDS_FIX" = "false" ]; then
    log_success "Tudo OK! Frontend deve conseguir acessar o backend."
    exit 0
elif [ "$NEEDS_FIX" = "true" ]; then
    log_warning "Correção aplicada. Reinicie o frontend para aplicar mudanças."
    exit 0
else
    log_warning "Alguns problemas podem persistir. Verifique manualmente."
    exit 1
fi

