#!/bin/bash
# scripts/deploy-local-to-vm.sh
# Deploy local para VM (simula GitHub Actions)
# Execute após validar com test-local-deploy.sh
# Baseado no Checklist 100% deploy funcionando

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configurações
VM_IP="${VM_IP:-}"
VM_USER="${VM_USER:-azureuser}"
# Tentar encontrar chave SSH: primeiro em keys/azure, depois em ~/.ssh
if [ -z "${SSH_KEY:-}" ]; then
    if [ -f "$PROJECT_DIR/keys/azure/id_rsa" ]; then
        SSH_KEY="$PROJECT_DIR/keys/azure/id_rsa"
    elif [ -f "$PROJECT_DIR/keys/azure/team/id_rsa_poc" ]; then
        SSH_KEY="$PROJECT_DIR/keys/azure/team/id_rsa_poc"
    elif [ -f "$HOME/.ssh/id_rsa" ]; then
        SSH_KEY="$HOME/.ssh/id_rsa"
    elif [ -f "$HOME/.ssh/id_ed25519" ]; then
        SSH_KEY="$HOME/.ssh/id_ed25519"
    else
        SSH_KEY=""
    fi
fi
BRANCH="${BRANCH:-staging}"
REPO_OWNER="${REPO_OWNER:-sky-first}"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

ERRORS=0

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; ERRORS=$((ERRORS + 1)); }
log_section() { echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${CYAN}▶ $1${NC}"; echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }

# Validar parâmetros
if [ -z "$VM_IP" ]; then
    log_error "VM_IP não definido"
    echo ""
    echo "Use:"
    echo "  export VM_IP=172.191.77.30"
    echo "  export BRANCH=staging  # opcional (padrão: staging)"
    echo "  export GH_PAT=seu_token  # opcional (necessário se repositórios forem privados)"
    echo "  ./scripts/deploy-local-to-vm.sh"
    exit 1
fi

if [ -z "$SSH_KEY" ] || [ ! -f "$SSH_KEY" ]; then
    log_error "Chave SSH não encontrada"
    echo ""
    log_info "Locais verificados:"
    echo "  - $PROJECT_DIR/keys/azure/id_rsa"
    echo "  - $PROJECT_DIR/keys/azure/team/id_rsa_poc"
    echo "  - $HOME/.ssh/id_rsa"
    echo "  - $HOME/.ssh/id_ed25519"
    echo ""
    log_info "Soluções:"
    echo "  1. Configure manualmente: export SSH_KEY=/caminho/para/chave"
    echo "  2. Exemplo: export SSH_KEY=$PROJECT_DIR/keys/azure/team/id_rsa_poc"
    echo "  3. Ou: export SSH_KEY=$HOME/.ssh/id_ed25519"
    echo ""
    exit 1
fi

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════╗"
echo "║     Deploy Local para VM                            ║"
echo "║     Simulando GitHub Actions (Fase 2)               ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${NC}"

log_info "Configurações:"
echo "  VM IP: $VM_IP"
echo "  VM User: $VM_USER"
echo "  Branch: $BRANCH"
echo "  Repo Owner: $REPO_OWNER"
echo "  SSH Key: $SSH_KEY"
echo ""

# ============================================
# 1. VALIDAR ACESSO À VM
# ============================================
log_section "1. Validando Acesso à VM (Checklist Item 4)"

# Testar conexão SSH com opções mais tolerantes
SSH_OPTS="-i \"$SSH_KEY\" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

if ssh $SSH_OPTS "$VM_USER@$VM_IP" "echo 'OK'" 2>&1 | grep -q "OK"; then
    log_success "Conectado à VM: $VM_IP"
else
    # Tentar novamente sem redirecionar stderr para ver o erro
    log_info "Testando conexão SSH..."
    SSH_ERROR=$(ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$VM_USER@$VM_IP" "echo 'OK'" 2>&1)
    
    if echo "$SSH_ERROR" | grep -q "OK"; then
        log_success "Conectado à VM: $VM_IP"
    else
        log_error "Não foi possível conectar à VM"
        log_info "Erro SSH: $SSH_ERROR"
        log_info ""
        log_info "Verifique:"
        log_info "  - VM está rodando? (az vm show -d -g <rg> -n <vm> --query powerState)"
        log_info "  - IP está correto: $VM_IP"
        log_info "  - Chave SSH está correta: $SSH_KEY"
        log_info "  - Firewall/NSG permite SSH na porta 22?"
        log_info ""
        log_info "Teste manualmente:"
        log_info "  ssh -i $SSH_KEY $VM_USER@$VM_IP 'echo OK'"
        exit 1
    fi
fi

# ============================================
# 2. VALIDAR PRÉ-REQUISITOS NA VM
# ============================================
log_section "2. Validando Pré-requisitos na VM (Checklist Item 4)"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$VM_USER@$VM_IP" "
    set -eu
    
    echo 'Verificando Docker...'
    if ! command -v docker &>/dev/null; then
        echo 'ERRO: Docker não instalado'
        exit 1
    fi
    docker --version
    
    echo 'Verificando Docker Compose...'
    if ! command -v docker compose &>/dev/null && ! command -v docker-compose &>/dev/null; then
        echo 'ERRO: Docker Compose não instalado'
        exit 1
    fi
    docker compose version 2>/dev/null || docker-compose --version
    
    echo 'Verificando Git...'
    if ! command -v git &>/dev/null; then
        echo 'ERRO: Git não instalado'
        exit 1
    fi
    git --version
    
    echo 'Verificando permissões Docker...'
    if ! sudo docker ps &>/dev/null; then
        echo 'ERRO: azureuser não consegue executar sudo docker'
        echo 'SOLUÇÃO: sudo usermod -aG docker azureuser && newgrp docker'
        exit 1
    fi
    echo 'OK: Permissões Docker OK'
    
    echo 'Verificando se Docker está rodando...'
    if ! sudo systemctl is-active --quiet docker 2>/dev/null && ! docker ps &>/dev/null; then
        echo 'ERRO: Docker não está rodando'
        echo 'SOLUÇÃO: sudo systemctl start docker'
        exit 1
    fi
    echo 'OK: Docker está rodando'
" || {
    log_error "Pré-requisitos na VM não atendidos"
    exit 1
}

log_success "Pré-requisitos na VM OK"

# ============================================
# 3. CRIAR/VALIDAR ESTRUTURA DE DIRETÓRIOS
# ============================================
log_section "3. Criando Estrutura de Diretórios (Checklist Item 3)"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$VM_USER@$VM_IP" "
    set -eu
    
    BASE=~/projeto
    mkdir -p \"\$BASE\" || { echo '[ERROR] Erro ao criar ~/projeto'; exit 1; }
    
    # Criar diretórios necessários
    mkdir -p \"\$BASE/sky-poc-infra\"
    mkdir -p \"\$BASE/sky-poc-backend\"
    mkdir -p \"\$BASE/sky-poc-frontend\"
    mkdir -p \"\$BASE/sky-poc-ai\"
    
    echo '[OK] Estrutura de diretórios criada'
    echo 'Diretórios:'
    ls -la \"\$BASE\" | grep -E 'sky-poc|poc-deploy' || true
" || {
    log_error "Falha ao criar estrutura de diretórios"
    exit 1
}

log_success "Estrutura de diretórios criada"

# ============================================
# 4. CONFIGURAR AUTENTICAÇÃO GIT NA VM
# ============================================
log_section "4. Configurando Autenticação Git na VM (Checklist Item 1)"

if [ -n "${GH_PAT:-}" ]; then
    log_info "Configurando autenticação Git com GH_PAT"
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$VM_USER@$VM_IP" "
        set -eu
        git config --global url.\"https://x-access-token:${GH_PAT}@github.com/\".insteadOf \"https://github.com/\"
        echo '[OK] Autenticação Git configurada (PAT)'
    " || {
        log_error "Falha ao configurar autenticação Git"
        exit 1
    }
    log_success "Autenticação Git configurada"
    # Usar URL com token para clonar
    REPO_URL_PREFIX="https://x-access-token:${GH_PAT}@github.com/"
else
    log_error "GH_PAT não configurado - necessário para repositórios privados"
    log_info "Configure o GH_PAT antes de continuar:"
    log_info "  export GH_PAT=ghp_seu_token_aqui"
    log_info ""
    log_info "Para criar um token:"
    log_info "  1. GitHub > Settings > Developer settings > Personal access tokens > Tokens (classic)"
    log_info "  2. Generate new token (classic)"
    log_info "  3. Selecione escopo: repo (acesso completo aos repositórios)"
    exit 1
fi

# ============================================
# 5. CLONAR/ATUALIZAR REPOSITÓRIOS
# ============================================
log_section "5. Clonando/Atualizando Repositórios (Checklist Item 1)"

REPOS=(
    "sky-first/sky-poc-infra:sky-poc-infra"
    "sky-first/sky-poc-backend:sky-poc-backend"
    "sky-first/sky-poc-frontend:sky-poc-frontend"
    "sky-first/sky-poc-ai:sky-poc-ai"
)

for repo_info in "${REPOS[@]}"; do
    if [ -n "${GH_PAT:-}" ]; then
        REPO_URL="https://x-access-token:${GH_PAT}@github.com/${repo_info%%:*}.git"
    else
        REPO_URL="https://github.com/${repo_info%%:*}.git"
    fi
    DIR_NAME="${repo_info##*:}"
    
    log_info "Processando: $DIR_NAME"
    
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$VM_USER@$VM_IP" "
        set -eu
        cd ~/projeto
        
        if [ -d \"$DIR_NAME\" ]; then
            echo 'Atualizando repositório existente...'
            cd \"$DIR_NAME\"
            
            # Verificar se é repositório git válido
            if [ ! -d .git ]; then
                echo '[WARNING] Diretório existe mas não é repositório Git, removendo...'
                cd ..
                rm -rf \"$DIR_NAME\"
                echo 'Clonando repositório...'
                # Remover token da URL para ls-remote (segurança)
                REPO_URL_CLEAN=\"\$(echo '$REPO_URL' | sed 's|https://x-access-token:[^@]*@|https://|')\"
                if git ls-remote --heads \"\$REPO_URL_CLEAN\" $BRANCH 2>/dev/null | grep -q $BRANCH; then
                    git clone -b $BRANCH \"$REPO_URL\" \"$DIR_NAME\" || { echo '[ERROR] Erro ao clonar'; exit 1; }
                    echo '[OK] Repositório clonado'
                else
                    echo \"[WARNING] Branch $BRANCH não encontrada, tentando main...\"
                    if git ls-remote --heads \"\$REPO_URL_CLEAN\" main 2>/dev/null | grep -q main; then
                        git clone -b main \"$REPO_URL\" \"$DIR_NAME\" || { echo '[ERROR] Erro ao clonar'; exit 1; }
                        echo '[OK] Repositório clonado (branch main)'
                    else
                        echo \"ERRO: Branches $BRANCH e main não encontradas\"
                        echo \"Branches disponíveis:\"
                        git ls-remote --heads \"\$REPO_URL_CLEAN\" 2>/dev/null | sed 's/.*refs\/heads\///' || true
                        exit 1
                    fi
                fi
            else
                git fetch origin || { echo '[ERROR] Erro ao fazer fetch'; exit 1; }
                
                if git ls-remote --heads origin $BRANCH | grep -q $BRANCH; then
                    git checkout $BRANCH || { echo '[ERROR] Erro ao fazer checkout'; exit 1; }
                    git pull origin $BRANCH || { echo '[ERROR] Erro ao fazer pull'; exit 1; }
                    echo '[OK] Repositório atualizado'
                else
                    echo \"ERRO: Branch $BRANCH não encontrada\"
                    echo \"Branches disponíveis:\"
                    git ls-remote --heads origin | sed 's/.*refs\/heads\///' || true
                    exit 1
                fi
            fi
        else
            echo 'Clonando repositório...'
            # Remover token da URL para ls-remote (segurança)
            REPO_URL_CLEAN=\"\$(echo '$REPO_URL' | sed 's|https://x-access-token:[^@]*@|https://|')\"
            if git ls-remote --heads \"\$REPO_URL_CLEAN\" $BRANCH 2>/dev/null | grep -q $BRANCH; then
                git clone -b $BRANCH \"$REPO_URL\" \"$DIR_NAME\" || { echo '[ERROR] Erro ao clonar'; exit 1; }
                echo '[OK] Repositório clonado (branch $BRANCH)'
            else
                echo \"[WARNING] Branch $BRANCH não encontrada, tentando main...\"
                if git ls-remote --heads \"\$REPO_URL_CLEAN\" main 2>/dev/null | grep -q main; then
                    git clone -b main \"$REPO_URL\" \"$DIR_NAME\" || { echo '[ERROR] Erro ao clonar'; exit 1; }
                    echo '[OK] Repositório clonado (branch main)'
                else
                    echo \"ERRO: Branches $BRANCH e main não encontradas\"
                    echo \"Branches disponíveis:\"
                    git ls-remote --heads \"\$REPO_URL_CLEAN\" 2>/dev/null | sed 's/.*refs\/heads\///' || true
                    exit 1
                fi
            fi
        fi
    " || {
        log_error "Falha ao processar $DIR_NAME"
        exit 1
    }
done

log_success "Repositórios atualizados"

# ============================================
# 6. ESCREVER .ENV NA VM
# ============================================
log_section "6. Escrevendo .env na VM (Checklist Item 2)"

if [ ! -f "$PROJECT_DIR/.env" ]; then
    log_error ".env não encontrado localmente"
    log_info "Crie o .env antes de fazer deploy:"
    log_info "  cd sky-poc-infra"
    log_info "  cp env.example .env"
    log_info "  ./scripts/fix-env-secrets.sh  # Gera senhas seguras"
    exit 1
fi

log_info "Enviando .env para VM..."

# Codificar .env em base64 e enviar
ENV_B64=$(base64 -i "$PROJECT_DIR/.env" 2>/dev/null || base64 "$PROJECT_DIR/.env" | tr -d '\n')

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$VM_USER@$VM_IP" "
    set -eu
    BASE=~/projeto/sky-poc-infra
    mkdir -p \"\$BASE\" || { echo '[ERROR] Erro ao criar diretório'; exit 1; }
    
    echo '$ENV_B64' | base64 -d > \"\$BASE/.env\" || { echo '[ERROR] Erro ao escrever .env'; exit 1; }
    chmod 600 \"\$BASE/.env\" || { echo '[ERROR] Erro ao definir permissões'; exit 1; }
    echo '[OK] Arquivo .env criado'
    
    # Validar variáveis obrigatórias
    MISSING=''
    for var in POSTGRES_PASSWORD REDIS_PASSWORD JWT_SECRET_KEY ENCRYPTION_KEY; do
        if ! grep -q \"^\$var=\" \"\$BASE/.env\"; then
            MISSING=\"\$MISSING \$var\"
        fi
    done
    
    if [ -n \"\$MISSING\" ]; then
        echo \"ERRO: Variáveis faltando no .env:\$MISSING\"
        exit 1
    fi
    
    echo '[OK] Variáveis obrigatórias validadas'
" || {
    log_error "Falha ao escrever .env na VM"
    exit 1
}

log_success ".env escrito e validado na VM"

# ============================================
# 7. VALIDAR DOCKER COMPOSE PATHS
# ============================================
log_section "7. Validando Docker Compose Paths (Checklist Item 3)"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$VM_USER@$VM_IP" "
    set -eu
    cd ~/projeto/sky-poc-infra
    
    if [ ! -f docker-compose.yml ]; then
        echo '[ERROR] ERRO: docker-compose.yml não encontrado'
        exit 1
    fi
    
    # Validar contexts
    if [ ! -d ../sky-poc-backend ]; then
        echo '[ERROR] ERRO: ../sky-poc-backend não encontrado'
        exit 1
    fi
    
    if [ ! -d ../sky-poc-frontend ]; then
        echo '[ERROR] ERRO: ../sky-poc-frontend não encontrado'
        exit 1
    fi
    
    if [ ! -d ../sky-poc-ai ]; then
        echo '[ERROR] ERRO: ../sky-poc-ai não encontrado'
        exit 1
    fi
    
    echo '[OK] Todos os caminhos validados'
" || {
    log_error "Validação de paths falhou"
    exit 1
}

log_success "Docker Compose paths validados"

# ============================================
# 8. VALIDAR BUILD ANTES DE SUBIR (FAIL FAST)
# ============================================
log_section "8. Validando Build Antes de Subir Containers (Fail Fast)"

log_info "Validando build do frontend antes de subir containers..."
if ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$VM_USER@$VM_IP" "
    set -eu
    cd ~/projeto/sky-poc-frontend
    if [ -f package.json ] && command -v npm &>/dev/null; then
        echo 'Instalando dependências...'
        npm ci --silent || npm install --silent
        echo 'Executando build...'
        npm run build 2>&1
    else
        echo '[WARNING] npm não disponível ou package.json não encontrado'
        exit 0
    fi
" 2>&1 | tee /tmp/frontend-build-validate.log; then
    if grep -q "Build error\|Error\|failed\|Failed" /tmp/frontend-build-validate.log; then
        log_error "Build do frontend falhou na validação"
        log_info "Corrija os erros antes de continuar"
        log_info "Logs do build:"
        grep -A 10 -E "(error|Error|ERROR|failed|Failed)" /tmp/frontend-build-validate.log | head -30
        exit 1
    else
        log_success "Build do frontend validado"
    fi
else
    log_warning "Não foi possível validar build (npm pode não estar disponível na VM)"
    log_info "Continuando com deploy (build será validado durante docker compose build)"
fi

# ============================================
# 9. SUBIR CONTAINERS
# ============================================
log_section "9. Subindo Containers (Checklist Item 7)"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$VM_USER@$VM_IP" "
    set -eu
    cd ~/projeto/sky-poc-infra
    
    echo 'Parando containers existentes...'
    sudo docker compose down || echo 'Nenhum container rodando para parar'
    
    echo 'Construindo e iniciando containers...'
    sudo docker compose up -d --build || {
        echo '[ERROR] ERRO: Falha ao iniciar containers'
        echo 'Logs dos containers:'
        sudo docker compose logs --tail=50
        exit 1
    }
    
    echo '[OK] Containers iniciados'
    echo ''
    echo 'Status dos containers:'
    sudo docker compose ps
" || {
    log_error "Falha ao subir containers"
    exit 1
}

log_success "Containers subidos"

# ============================================
# 9. HEALTH CHECK
# ============================================
log_section "9. Health Check (Checklist Item 8)"

log_info "Aguardando containers iniciarem..."
sleep 30

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$VM_USER@$VM_IP" "
    set -eu
    
    echo 'Verificando Postgres...'
    POSTGRES_CONTAINER=\$(sudo docker ps --format '{{.Names}}' | grep postgres | head -1)
    if [ -n \"\$POSTGRES_CONTAINER\" ]; then
        if sudo docker exec \"\$POSTGRES_CONTAINER\" pg_isready -U postgres &>/dev/null; then
            echo '[OK] Postgres: OK'
        else
            echo '[ERROR] Postgres: Não responde'
            exit 1
        fi
    else
        echo '[WARNING] Postgres: Container não encontrado'
    fi
    
    echo 'Verificando Redis...'
    REDIS_CONTAINER=\$(sudo docker ps --format '{{.Names}}' | grep redis | head -1)
    if [ -n \"\$REDIS_CONTAINER\" ]; then
        REDIS_PASS=\$(grep REDIS_PASSWORD ~/projeto/sky-poc-infra/.env | cut -d'=' -f2 || echo '')
        if [ -n \"\$REDIS_PASS\" ]; then
            if sudo docker exec \"\$REDIS_CONTAINER\" redis-cli -a \"\$REDIS_PASS\" ping | grep -q PONG; then
                echo '[OK] Redis: OK'
            else
                echo '[ERROR] Redis: Não responde'
                exit 1
            fi
        else
            echo '[WARNING] Redis: Senha não encontrada no .env'
        fi
    else
        echo '[WARNING] Redis: Container não encontrado'
    fi
    
    echo 'Verificando Backend...'
    BACKEND_CONTAINER=\$(sudo docker ps --format '{{.Names}}' | grep backend | head -1)
    if [ -n \"\$BACKEND_CONTAINER\" ]; then
        sleep 10  # Aguardar backend iniciar
        if curl -f http://localhost:8000/health &>/dev/null || \
           curl -f http://localhost:8000/api/health &>/dev/null || \
           curl -f http://localhost:8000/ &>/dev/null; then
            echo '[OK] Backend: OK'
        else
            echo '[WARNING] Backend: Pode estar iniciando ainda'
            echo 'Logs do backend:'
            sudo docker logs \"\$BACKEND_CONTAINER\" --tail=20 || true
        fi
    else
        echo '[WARNING] Backend: Container não encontrado'
    fi
    
    echo 'Verificando Frontend...'
    FRONTEND_CONTAINER=\$(sudo docker ps --format '{{.Names}}' | grep frontend | head -1)
    if [ -n \"\$FRONTEND_CONTAINER\" ]; then
        echo '[OK] Frontend: Container rodando'
    else
        echo '[WARNING] Frontend: Container não encontrado'
    fi
    
    echo 'Verificando Proxy/Nginx...'
    PROXY_CONTAINER=\$(sudo docker ps --format '{{.Names}}' | grep -E 'proxy|nginx' | head -1)
    if [ -n \"\$PROXY_CONTAINER\" ]; then
        if curl -f http://localhost/health &>/dev/null || curl -f http://localhost/ &>/dev/null; then
            echo '[OK] Proxy: OK'
        else
            echo '[WARNING] Proxy: Pode estar iniciando ainda'
        fi
    else
        echo '[WARNING] Proxy: Container não encontrado'
    fi
    
    echo '[OK] Health check concluído'
" || {
    log_error "Alguns health checks falharam"
    log_info "Containers podem estar ainda iniciando. Verifique os logs."
}

# ============================================
# 10. RESUMO FINAL
# ============================================
log_section "Deploy Concluído"

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}[OK][OK][OK] Deploy local para VM concluído com sucesso!${NC}"
    echo ""
    echo -e "${CYAN}Informações:${NC}"
    echo "  VM IP: $VM_IP"
    echo "  Frontend: http://$VM_IP"
    echo "  API: http://$VM_IP/api/v1"
    echo "  Health Check: http://$VM_IP/api/v1/health"
    echo ""
    echo -e "${YELLOW}Comandos úteis:${NC}"
    echo "  # Ver logs:"
    echo "  ssh -i $SSH_KEY $VM_USER@$VM_IP 'cd ~/projeto/sky-poc-infra && sudo docker compose logs'"
    echo ""
    echo "  # Ver status dos containers:"
    echo "  ssh -i $SSH_KEY $VM_USER@$VM_IP 'cd ~/projeto/sky-poc-infra && sudo docker compose ps'"
    echo ""
    echo "  # Ver logs de um container específico:"
    echo "  ssh -i $SSH_KEY $VM_USER@$VM_IP 'cd ~/projeto/sky-poc-infra && sudo docker compose logs backend'"
    echo ""
    echo -e "${CYAN}Próximo passo:${NC}"
    echo "  Se tudo OK, configure GitHub Actions para deploy automático (Fase 3)"
    exit 0
else
    echo -e "${RED}[ERROR] Deploy concluído com $ERRORS erro(s)${NC}"
    echo -e "${RED}Verifique os logs acima para mais detalhes${NC}"
    exit 1
fi

