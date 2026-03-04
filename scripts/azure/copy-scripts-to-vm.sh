#!/bin/bash
# Script DevOps: Copia scripts novos para a VM
# Uso: ./scripts/azure/copy-scripts-to-vm.sh [VM_IP] [SSH_KEY]

set -eu

VM_IP="${1:-20.86.142.1}"
SSH_KEY="${2:-keys/azure/team/id_rsa_poc}"
VM_USER="azureuser"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

echo "=========================================="
echo "📦 Copiando Scripts para VM"
echo "=========================================="
echo ""
echo "VM IP: $VM_IP"
echo "SSH Key: $SSH_KEY"
echo ""

# Verificar se chave SSH existe
if [ ! -f "$SSH_KEY" ]; then
    log_error "Chave SSH não encontrada: $SSH_KEY"
    exit 1
fi

# Scripts a copiar
SCRIPTS=(
    "scripts/azure/fix-next-public-api-url.sh"
    "scripts/azure/diagnose-frontend-backend-error.sh"
)

# Verificar se scripts existem localmente
for script in "${SCRIPTS[@]}"; do
    if [ ! -f "$script" ]; then
        log_error "Script não encontrado localmente: $script"
        exit 1
    fi
done

log_success "Scripts encontrados localmente"
echo ""

# Testar conexão SSH
log_info "Testando conexão SSH..."
if ! ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$VM_USER@$VM_IP" "echo 'OK'" &>/dev/null; then
    log_error "Não foi possível conectar à VM"
    exit 1
fi
log_success "Conectado à VM"
echo ""

# Encontrar diretório do projeto na VM
log_info "Encontrando diretório do projeto na VM..."
PROJECT_DIR=$(ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
    if [ -d ~/projeto/sky-poc-infra ]; then
        echo ~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        echo ~/projeto/poc-deploy
    else
        echo 'NOT_FOUND'
    fi
" 2>/dev/null || echo "NOT_FOUND")

if [ "$PROJECT_DIR" = "NOT_FOUND" ]; then
    log_error "Diretório do projeto não encontrado na VM"
    log_info "Criando diretório..."
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "mkdir -p ~/projeto/sky-poc-infra/scripts/azure"
    PROJECT_DIR="~/projeto/sky-poc-infra"
fi

log_success "Diretório do projeto: $PROJECT_DIR"
echo ""

# Copiar scripts
log_info "Copiando scripts para a VM..."
for script in "${SCRIPTS[@]}"; do
    script_name=$(basename "$script")
    log_info "Copiando $script_name..."
    
    # Criar diretório se não existir
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "mkdir -p $PROJECT_DIR/scripts/azure" 2>/dev/null
    
    # Copiar arquivo
    scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$script" "$VM_USER@$VM_IP:$PROJECT_DIR/scripts/azure/" 2>/dev/null
    
    # Tornar executável
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "chmod +x $PROJECT_DIR/scripts/azure/$script_name" 2>/dev/null
    
    log_success "$script_name copiado e configurado"
done

echo ""
echo "=========================================="
echo "✅ Scripts Copiados com Sucesso"
echo "=========================================="
echo ""
echo "Agora você pode executar na VM:"
echo ""
echo "  cd $PROJECT_DIR"
echo "  ./scripts/azure/diagnose-frontend-backend-error.sh"
echo ""
echo "Ou:"
echo ""
echo "  ./scripts/azure/fix-next-public-api-url.sh"
echo ""

