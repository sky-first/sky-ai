#!/bin/bash
# scripts/setup-vm-production.sh
# Script profissional para configurar VM de produção
# Configura .env, valida estrutura, prepara ambiente

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configurações
VM_IP="${VM_IP:-172.191.77.30}"
VM_USER="azureuser"
SSH_KEY="${SSH_KEY:-$PROJECT_DIR/keys/azure/id_rsa}"
PROJECT_PATH="~/projeto/poc-deploy"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo -e "${CYAN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Configuração VM Produção                     ║${NC}"
echo -e "${CYAN}║     VM: $VM_IP                                  ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════╝${NC}"
echo ""

# 1. Verificar conectividade
log_info "Verificando conectividade..."
if ! ssh -i "$SSH_KEY" -o ConnectTimeout=5 "$VM_USER@$VM_IP" "echo 'OK'" &>/dev/null; then
    log_error "Não foi possível conectar à VM"
    exit 1
fi
log_success "Conectado à VM"

# 2. Verificar estrutura
log_info "Verificando estrutura de pastas..."
STRUCTURE=$(ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
    cd ~/projeto 2>/dev/null || { echo 'MISSING'; exit 1; }
    if [ -d poc-deploy ]; then
        echo 'poc-deploy'
    elif [ -d sky-poc-infra ]; then
        echo 'sky-poc-infra'
    else
        echo 'MISSING'
    fi
")

if [ "$STRUCTURE" = "MISSING" ]; then
    log_error "Estrutura de projeto não encontrada em ~/projeto/"
    log_info "Execute o deploy via Terraform primeiro"
    exit 1
fi

log_success "Estrutura encontrada: $STRUCTURE"
PROJECT_PATH="~/projeto/$STRUCTURE"

# 3. Verificar/criar .env
log_info "Verificando arquivo .env..."
ENV_EXISTS=$(ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
    cd $PROJECT_PATH 2>/dev/null && [ -f .env ] && echo 'YES' || echo 'NO'
")

if [ "$ENV_EXISTS" = "NO" ]; then
    log_warning ".env não encontrado, criando a partir de env.example..."
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        cd $PROJECT_PATH || exit 1
        if [ -f env.example ]; then
            cp env.example .env
            chmod 600 .env
            echo 'Arquivo .env criado'
        else
            echo 'ERRO: env.example não encontrado'
            exit 1
        fi
    "
    log_warning "IMPORTANTE: Configure o .env com valores reais antes do deploy!"
    log_info "Edite: ssh $VM_USER@$VM_IP 'nano $PROJECT_PATH/.env'"
else
    log_success ".env já existe"
fi

# 4. Atualizar NEXT_PUBLIC_API_URL
log_info "Atualizando NEXT_PUBLIC_API_URL..."
ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
    cd $PROJECT_PATH || exit 1
    if grep -q 'NEXT_PUBLIC_API_URL' .env; then
        sed -i 's|NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=http://$VM_IP/api/v1|' .env
        echo 'NEXT_PUBLIC_API_URL atualizado'
    else
        echo 'NEXT_PUBLIC_API_URL=http://$VM_IP/api/v1' >> .env
        echo 'NEXT_PUBLIC_API_URL adicionado'
    fi
" && log_success "NEXT_PUBLIC_API_URL configurado"

# 5. Verificar Docker
log_info "Verificando Docker..."
if ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "docker --version" &>/dev/null; then
    DOCKER_VERSION=$(ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "docker --version")
    log_success "Docker: $DOCKER_VERSION"
else
    log_error "Docker não está instalado"
    exit 1
fi

# 6. Verificar espaço em disco
log_info "Verificando espaço em disco..."
DISK_INFO=$(ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "df -h / | tail -1 | awk '{print \$4}'")
log_info "Espaço livre: $DISK_INFO"

# 7. Resumo
echo ""
log_success "Configuração concluída!"
echo ""
echo -e "${CYAN}Informações:${NC}"
echo "  VM IP: $VM_IP"
echo "  Projeto: $PROJECT_PATH"
echo "  Frontend URL: http://$VM_IP"
echo "  API URL: http://$VM_IP/api/"
echo ""
echo -e "${YELLOW}Próximos passos:${NC}"
echo "  1. Configure .env com secrets reais (se necessário)"
echo "  2. Execute deploy: ./scripts/deploy-production.sh"
echo ""

