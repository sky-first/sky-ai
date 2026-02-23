#!/bin/bash
# scripts/validate-deploy-complete.sh
# Validação completa antes do deploy - verifica backend, frontend, IA e caminhos

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

ERRORS=0
WARNINGS=0

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[]${NC} $1"; WARNINGS=$((WARNINGS + 1)); }
log_error() { echo -e "${RED}[]${NC} $1"; ERRORS=$((ERRORS + 1)); }
log_section() { 
    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; 
    echo -e "${CYAN} $1${NC}"; 
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; 
}

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════╗"
echo "║     Validação Completa Pré-Deploy                 ║"
echo "║     Backend, Frontend, IA e Caminhos               ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ============================================
# 1. ESTRUTURA DE PASTAS
# ============================================
log_section "1. Validando Estrutura de Pastas"

# Verificar diretório atual
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    log_error "docker-compose.yml não encontrado"
    exit 1
fi
log_success "docker-compose.yml encontrado"

# Verificar repositórios necessários
REQUIRED_REPOS=(
    "../sky-poc-backend"
    "../sky-poc-frontend"
    "../sky-poc-ai"
)

for repo in "${REQUIRED_REPOS[@]}"; do
    full_path="$PROJECT_DIR/$repo"
    if [ ! -d "$full_path" ]; then
        log_error "$repo não encontrado"
    else
        log_success "$repo encontrado"
        
        # Verificar se tem Dockerfile
        if [[ "$repo" == *"backend"* ]]; then
            if [ -f "$full_path/docker/Dockerfile" ]; then
                log_success "  Dockerfile encontrado em $repo/docker/Dockerfile"
            else
                log_error "  Dockerfile não encontrado em $repo/docker/Dockerfile"
            fi
        elif [[ "$repo" == *"frontend"* ]]; then
            if [ -f "$full_path/docker/Dockerfile" ]; then
                log_success "  Dockerfile encontrado em $repo/docker/Dockerfile"
            else
                log_error "  Dockerfile não encontrado em $repo/docker/Dockerfile"
            fi
        fi
    fi
done

# ============================================
# 2. CAMINHOS NO DOCKER COMPOSE
# ============================================
log_section "2. Validando Caminhos no Docker Compose"

# Verificar contextos
BACKEND_CONTEXT=$(grep -A 2 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep "context:" | awk '{print $2}' | head -1)
FRONTEND_CONTEXT=$(grep -A 2 "frontend:" "$PROJECT_DIR/docker-compose.yml" | grep "context:" | awk '{print $2}' | head -1)

if [ -z "$BACKEND_CONTEXT" ]; then
    log_error "Contexto do backend não encontrado"
elif [ "$BACKEND_CONTEXT" = "../sky-poc-backend" ]; then
    log_success "Backend context correto: $BACKEND_CONTEXT"
    if [ -d "$PROJECT_DIR/$BACKEND_CONTEXT" ]; then
        log_success "  Diretório existe"
    else
        log_error "  Diretório não existe: $PROJECT_DIR/$BACKEND_CONTEXT"
    fi
elif [ "$BACKEND_CONTEXT" = "../backend" ]; then
    log_warning "Backend context usa nome antigo: $BACKEND_CONTEXT (deve ser ../sky-poc-backend)"
else
    log_warning "Backend context: $BACKEND_CONTEXT (verificar se está correto)"
fi

if [ -z "$FRONTEND_CONTEXT" ]; then
    log_error "Contexto do frontend não encontrado"
elif [ "$FRONTEND_CONTEXT" = "../sky-poc-frontend" ]; then
    log_success "Frontend context correto: $FRONTEND_CONTEXT"
    if [ -d "$PROJECT_DIR/$FRONTEND_CONTEXT" ]; then
        log_success "  Diretório existe"
    else
        log_error "  Diretório não existe: $PROJECT_DIR/$FRONTEND_CONTEXT"
    fi
elif [ "$FRONTEND_CONTEXT" = "../frontend" ]; then
    log_warning "Frontend context usa nome antigo: $FRONTEND_CONTEXT (deve ser ../sky-poc-frontend)"
else
    log_warning "Frontend context: $FRONTEND_CONTEXT (verificar se está correto)"
fi

# ============================================
# 3. DEPENDÊNCIAS ENTRE SERVIÇOS
# ============================================
log_section "3. Validando Dependências entre Serviços"

# Backend depende de postgres, redis, migrate
if grep -A 15 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "depends_on:"; then
    if grep -A 20 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "postgres:"; then
        log_success "Backend depende de PostgreSQL"
    fi
    if grep -A 20 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "redis:"; then
        log_success "Backend depende de Redis"
    fi
    if grep -A 20 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "migrate:"; then
        log_success "Backend depende de migrate"
    fi
else
    log_warning "Backend não tem depends_on configurado"
fi

# Frontend depende de backend
if grep -A 10 "frontend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "depends_on:"; then
    if grep -A 15 "frontend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "backend:"; then
        log_success "Frontend depende de Backend"
    fi
else
    log_warning "Frontend não tem depends_on configurado"
fi

# Worker e Beat dependem de postgres, redis, migrate
for service in "worker" "beat"; do
    if grep -A 20 "$service:" "$PROJECT_DIR/docker-compose.yml" | grep -q "depends_on:"; then
        log_success "$service tem depends_on configurado"
    else
        log_warning "$service não tem depends_on configurado"
    fi
done

# ============================================
# 4. REPOSITÓRIO IA (VERIFICAÇÃO ESPECIAL)
# ============================================
log_section "4. Verificando Repositório IA"

# IA geralmente não tem container próprio, mas pode ser usado pelo backend
if [ -d "$PROJECT_DIR/../sky-poc-ai" ]; then
    log_success "Repositório IA encontrado: ../sky-poc-ai"
    
    # Verificar se backend precisa montar IA como volume
    if grep -q "sky-poc-ai\|ia" "$PROJECT_DIR/docker-compose.yml"; then
        log_info "IA referenciado no docker-compose.yml"
        # Verificar se está montado como volume
        if grep -A 10 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "volumes:"; then
            VOLUMES=$(grep -A 10 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -A 5 "volumes:" | grep "ia\|sky-poc-ai")
            if [ -n "$VOLUMES" ]; then
                log_success "IA montado como volume no backend"
            else
                log_warning "IA não está montado como volume (pode ser necessário se backend usar)"
            fi
        else
            log_warning "Backend não tem volumes configurados (IA pode não estar acessível)"
        fi
    else
        log_warning "IA não referenciado no docker-compose.yml"
        log_info "  Se backend precisar acessar IA, adicione como volume:"
        log_info "  volumes:"
        log_info "    - ../sky-poc-ai:/app/ia:ro"
    fi
else
    log_warning "Repositório IA não encontrado: ../sky-poc-ai"
    log_info "  Se backend não usar IA, isso é normal"
fi

# ============================================
# 5. VARIÁVEIS DE AMBIENTE
# ============================================
log_section "5. Validando Variáveis de Ambiente"

if [ ! -f "$PROJECT_DIR/.env" ]; then
    log_warning ".env não encontrado (será criado de env.example)"
    if [ ! -f "$PROJECT_DIR/env.example" ]; then
        log_error "env.example não encontrado"
    fi
else
    log_success ".env encontrado"
    
    # Verificar variáveis críticas
    REQUIRED_VARS=(
        "POSTGRES_PASSWORD"
        "REDIS_PASSWORD"
        "JWT_SECRET_KEY"
        "ENCRYPTION_KEY"
    )
    
    for var in "${REQUIRED_VARS[@]}"; do
        if grep -q "^${var}=" "$PROJECT_DIR/.env"; then
            VALUE=$(grep "^${var}=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
            if [ -z "$VALUE" ] || [[ "$VALUE" == *"secure_password_here"* ]] || [[ "$VALUE" == *"generate"* ]]; then
                log_warning "$var não configurado (ainda tem placeholder)"
            else
                log_success "$var configurado"
            fi
        else
            log_warning "$var não encontrado no .env"
        fi
    done
    
    # Verificar NEXT_PUBLIC_API_URL
    if grep -q "^NEXT_PUBLIC_API_URL=" "$PROJECT_DIR/.env"; then
        API_URL=$(grep "^NEXT_PUBLIC_API_URL=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
        log_info "NEXT_PUBLIC_API_URL: $API_URL"
    else
        log_warning "NEXT_PUBLIC_API_URL não encontrado no .env"
    fi
fi

# ============================================
# 6. DOCKER COMPOSE VALIDATION
# ============================================
log_section "6. Validando Sintaxe Docker Compose"

if command -v docker &> /dev/null && docker ps &> /dev/null; then
    if docker compose -f "$PROJECT_DIR/docker-compose.yml" config &> /tmp/docker-compose-validation.log; then
        log_success "docker-compose.yml: sintaxe válida"
    else
        log_error "docker-compose.yml: erro de sintaxe"
        cat /tmp/docker-compose-validation.log | head -20
    fi
else
    log_warning "Docker não disponível para validação"
fi

# ============================================
# 7. TERRAFORM DEPLOY SCRIPT
# ============================================
log_section "7. Validando Script de Deploy Terraform"

if [ -f "$PROJECT_DIR/infra/azure/deploy.tf" ]; then
    log_success "deploy.tf encontrado"
    
    # Verificar se suporta ambos os nomes
    if grep -q "poc-deploy\|sky-poc-infra" "$PROJECT_DIR/infra/azure/deploy.tf"; then
        log_success "deploy.tf suporta ambos os nomes (poc-deploy e sky-poc-infra)"
    fi
    
    # Verificar se tenta clonar backend/frontend/ia
    if grep -q "sky-poc-backend\|backend" "$PROJECT_DIR/infra/azure/deploy.tf"; then
        log_success "deploy.tf tenta clonar backend"
    fi
    
    if grep -q "sky-poc-frontend\|frontend" "$PROJECT_DIR/infra/azure/deploy.tf"; then
        log_success "deploy.tf tenta clonar frontend"
    fi
    
    if grep -q "sky-poc-ai\|ia" "$PROJECT_DIR/infra/azure/deploy.tf"; then
        log_success "deploy.tf tenta clonar IA"
    fi
else
    log_warning "deploy.tf não encontrado"
fi

# ============================================
# RESUMO FINAL
# ============================================
log_section "Resumo da Validação"

echo -e "${BLUE}Erros encontrados: ${RED}$ERRORS${NC}"
echo -e "${BLUE}Avisos encontrados: ${YELLOW}$WARNINGS${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}[OK] Validação completa: TUDO OK!${NC}"
    echo -e "${GREEN}Pronto para deploy!${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}[WARNING] Validação completa com $WARNINGS aviso(s)${NC}"
    echo -e "${YELLOW}Recomendado revisar avisos antes do deploy${NC}"
    exit 0
else
    echo -e "${RED}[ERROR] Validação falhou com $ERRORS erro(s)${NC}"
    echo -e "${RED}Corrija os erros antes de continuar${NC}"
    exit 1
fi

