#!/bin/bash
# scripts/deploy-production.sh
# Script profissional de deploy para produção
# Segue melhores práticas DevOps: validação, backup, rollback, health checks

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configurações
VM_IP="${VM_IP:-172.191.77.30}"
VM_USER="azureuser"
SSH_KEY="${SSH_KEY:-$PROJECT_DIR/keys/azure/id_rsa}"
PROJECT_PATH="~/projeto/poc-deploy"
BACKUP_DIR="$PROJECT_DIR/backups/pre-deploy-$(date +%Y%m%d_%H%M%S)"

# Funções de logging
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}▶ $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Verificar pré-requisitos
check_prerequisites() {
    log_step "Verificando Pré-requisitos"
    
    local errors=0
    
    # Verificar SSH
    if [ ! -f "$SSH_KEY" ]; then
        log_error "Chave SSH não encontrada: $SSH_KEY"
        errors=$((errors + 1))
    fi
    
    # Verificar conectividade
    if ! ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$VM_USER@$VM_IP" "echo 'OK'" &>/dev/null; then
        log_error "Não foi possível conectar à VM: $VM_IP"
        log_info "Verifique: chave SSH, IP, firewall"
        errors=$((errors + 1))
    else
        log_success "Conectividade SSH OK"
    fi
    
    # Verificar Docker na VM
    if ! ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "command -v docker &> /dev/null"; then
        log_error "Docker não está instalado na VM"
        errors=$((errors + 1))
    else
        log_success "Docker instalado na VM"
    fi
    
    if [ $errors -gt 0 ]; then
        log_error "Pré-requisitos não atendidos. Abortando."
        exit 1
    fi
}

# Backup antes do deploy
create_backup() {
    log_step "Criando Backup Pré-Deploy"
    
    mkdir -p "$BACKUP_DIR"
    
    # Backup do .env (se existir na VM)
    log_info "Fazendo backup do .env..."
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        if [ -f $PROJECT_PATH/.env ]; then
            cat $PROJECT_PATH/.env
        fi
    " > "$BACKUP_DIR/.env.backup" 2>/dev/null || log_warning ".env não encontrado na VM"
    
    # Backup do estado dos containers
    log_info "Fazendo backup do estado dos containers..."
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        cd $PROJECT_PATH 2>/dev/null || exit 0
        docker compose ps --format json 2>/dev/null || echo '[]'
    " > "$BACKUP_DIR/containers-state.json" 2>/dev/null || true
    
    # Backup do banco (se PostgreSQL estiver rodando)
    log_info "Fazendo backup do PostgreSQL..."
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        cd $PROJECT_PATH 2>/dev/null || exit 0
        if docker ps | grep -q postgres; then
            docker exec ai_saas_postgres_prod pg_dump -U postgres ai_saas_db 2>/dev/null | gzip
        fi
    " > "$BACKUP_DIR/postgres-$(date +%Y%m%d_%H%M%S).sql.gz" 2>/dev/null || log_warning "PostgreSQL não está rodando ou backup falhou"
    
    log_success "Backup criado em: $BACKUP_DIR"
}

# Validar estrutura na VM
validate_vm_structure() {
    log_step "Validando Estrutura na VM"
    
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        cd $PROJECT_PATH 2>/dev/null || {
            echo 'ERRO: Diretório não encontrado'
            exit 1
        }
        
        # Verificar docker-compose.yml
        if [ ! -f docker-compose.yml ]; then
            echo 'ERRO: docker-compose.yml não encontrado'
            exit 1
        fi
        
        # Verificar repositórios (suporta ambos os nomes)
        MISSING=0
        if [ ! -d ../backend ] && [ ! -d ../sky-poc-backend ]; then
            echo 'AVISO: Backend não encontrado'
            MISSING=1
        fi
        if [ ! -d ../frontend ] && [ ! -d ../sky-poc-frontend ]; then
            echo 'AVISO: Frontend não encontrado'
            MISSING=1
        fi
        
        if [ \$MISSING -eq 1 ]; then
            echo 'AVISO: Alguns repositórios não foram encontrados'
            echo 'O deploy continuará, mas pode falhar se os repositórios não estiverem disponíveis'
        fi
        
        echo 'OK'
    " || {
        log_error "Validação da estrutura falhou"
        exit 1
    }
    
    log_success "Estrutura validada"
}

# Deploy na VM
deploy_to_vm() {
    log_step "Executando Deploy na VM"
    
    log_info "Parando containers existentes..."
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        cd $PROJECT_PATH || exit 1
        docker compose down || true
    " || log_warning "Falha ao parar containers (pode ser normal se não estiverem rodando)"
    
    log_info "Atualizando código..."
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        cd $PROJECT_PATH || exit 1
        git fetch origin || true
        git pull origin main || git pull origin \$(git branch --show-current) || true
    " || log_warning "Falha ao atualizar código (continuando...)"
    
    log_info "Construindo e iniciando containers..."
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        set -e
        cd $PROJECT_PATH || exit 1
        
        # Verificar se .env existe
        if [ ! -f .env ]; then
            echo 'AVISO: .env não encontrado, criando a partir de env.example...'
            cp env.example .env || {
                echo 'ERRO: env.example não encontrado'
                exit 1
            }
            echo 'IMPORTANTE: Configure o .env antes de continuar!'
            exit 1
        fi
        
        # Build e start
        echo 'Iniciando deploy...'
        docker compose up -d --build
        
        echo 'Aguardando containers iniciarem...'
        sleep 10
        
        # Verificar status
        docker compose ps
    " || {
        log_error "Deploy falhou"
        return 1
    }
    
    log_success "Deploy executado"
}

# Health checks
run_health_checks() {
    log_step "Executando Health Checks"
    
    local failed=0
    
    # Check PostgreSQL
    log_info "Verificando PostgreSQL..."
    if ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        cd $PROJECT_PATH
        docker exec ai_saas_postgres_prod pg_isready -U postgres 2>/dev/null
    "; then
        log_success "PostgreSQL: OK"
    else
        log_error "PostgreSQL: FALHOU"
        failed=$((failed + 1))
    fi
    
    # Check Redis
    log_info "Verificando Redis..."
    if ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        cd $PROJECT_PATH
        docker exec ai_saas_redis_prod redis-cli ping 2>/dev/null | grep -q PONG
    "; then
        log_success "Redis: OK"
    else
        log_error "Redis: FALHOU"
        failed=$((failed + 1))
    fi
    
    # Check Backend
    log_info "Verificando Backend..."
    sleep 5  # Aguardar backend iniciar
    if ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        curl -f -s http://localhost:8000/health > /dev/null 2>&1 || \
        curl -f -s http://localhost:8000/api/health > /dev/null 2>&1 || \
        curl -f -s http://localhost:8000/ > /dev/null 2>&1
    "; then
        log_success "Backend: OK"
    else
        log_warning "Backend: Pode não estar totalmente pronto (verifique logs)"
    fi
    
    # Check Frontend
    log_info "Verificando Frontend..."
    if ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        curl -f -s http://localhost:3000 > /dev/null 2>&1
    "; then
        log_success "Frontend: OK"
    else
        log_warning "Frontend: Pode não estar totalmente pronto (verifique logs)"
    fi
    
    # Check Nginx
    log_info "Verificando Nginx..."
    if ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        curl -f -s http://localhost:80 > /dev/null 2>&1 || \
        curl -f -s http://localhost > /dev/null 2>&1
    "; then
        log_success "Nginx: OK"
    else
        log_warning "Nginx: Pode não estar rodando (verifique se está no docker-compose.yml)"
    fi
    
    if [ $failed -gt 0 ]; then
        log_error "$failed serviço(s) falharam no health check"
        return 1
    fi
}

# Rollback em caso de falha
rollback() {
    log_step "Executando Rollback"
    
    log_info "Restaurando estado anterior..."
    ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "
        cd $PROJECT_PATH || exit 1
        git checkout HEAD~1 || true
        docker compose down || true
        docker compose up -d || true
    " || log_error "Rollback pode ter falhado"
    
    log_warning "Verifique manualmente o estado da aplicação"
}

# Main
main() {
    echo -e "${CYAN}"
    echo "╔════════════════════════════════════════════════════╗"
    echo "║     Deploy Profissional - Produção                ║"
    echo "║     VM: $VM_IP                                    ║"
    echo "╚════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    
    # Confirmar
    read -p "Continuar com deploy em produção? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_info "Deploy cancelado pelo usuário"
        exit 0
    fi
    
    # Executar etapas
    check_prerequisites
    create_backup
    validate_vm_structure
    
    if deploy_to_vm; then
        if run_health_checks; then
            log_success "Deploy concluído com sucesso!"
            echo ""
            log_info "URLs de acesso:"
            echo "  Frontend: http://$VM_IP"
            echo "  API: http://$VM_IP/api/"
            echo ""
            log_info "Backup disponível em: $BACKUP_DIR"
        else
            log_error "Health checks falharam"
            rollback
            exit 1
        fi
    else
        log_error "Deploy falhou"
        rollback
        exit 1
    fi
}

# Executar
main "$@"

