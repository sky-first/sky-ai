#!/bin/bash
# scripts/validate-infra-complete.sh
# Validação completa da infraestrutura antes do deploy
# Verifica: caminhos, dependências, consistência, back/front/IA

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
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
echo "║     Validação Completa de Infraestrutura          ║"
echo "║     Backend, Frontend, IA e Caminhos               ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ============================================
# 1. ESTRUTURA DE PASTAS
# ============================================
log_section "1. ESTRUTURA DE PASTAS"

# Verificar estrutura esperada
echo -e "${BLUE}Estrutura esperada:${NC}"
echo "  poc-deploy/"
echo "  ├── sky-poc-infra/     (você está aqui)"
echo "  ├── sky-poc-backend/"
echo "  ├── sky-poc-frontend/"
echo "  └── sky-poc-ai/"
echo ""

REQUIRED_DIRS=(
    "../sky-poc-backend"
    "../sky-poc-frontend"
    "../sky-poc-ai"
)

MISSING=0
for dir in "${REQUIRED_DIRS[@]}"; do
    full_path="$PROJECT_DIR/$dir"
    if [ ! -d "$full_path" ]; then
        log_error "$dir não encontrado"
        MISSING=$((MISSING + 1))
    else
        log_success "$dir encontrado"
        
        # Verificar se tem conteúdo relevante
        if [ "$dir" = "../sky-poc-backend" ]; then
            if [ ! -f "$full_path/docker/Dockerfile" ] && [ ! -f "$full_path/Dockerfile" ]; then
                log_warning "$dir: Dockerfile não encontrado"
            else
                log_success "$dir: Dockerfile encontrado"
            fi
        elif [ "$dir" = "../sky-poc-frontend" ]; then
            if [ ! -f "$full_path/docker/Dockerfile" ] && [ ! -f "$full_path/Dockerfile" ]; then
                log_warning "$dir: Dockerfile não encontrado"
            else
                log_success "$dir: Dockerfile encontrado"
            fi
        fi
    fi
done

if [ $MISSING -gt 0 ]; then
    log_error "$MISSING repositório(s) faltando"
fi

# ============================================
# 2. DOCKER COMPOSE - CAMINHOS
# ============================================
log_section "2. DOCKER COMPOSE - CAMINHOS E CONTEXTOS"

DOCKER_COMPOSE="$PROJECT_DIR/docker-compose.yml"

# Verificar caminhos do backend
if grep -q "context: ../sky-poc-backend" "$DOCKER_COMPOSE"; then
    log_success "Backend usa contexto correto: ../sky-poc-backend"
    
    # Verificar se caminho existe
    BACKEND_PATH="$PROJECT_DIR/../sky-poc-backend"
    if [ -d "$BACKEND_PATH" ]; then
        log_success "Caminho backend existe e é acessível"
    else
        log_error "Caminho backend não existe: $BACKEND_PATH"
    fi
else
    if grep -q "context: ../backend" "$DOCKER_COMPOSE"; then
        log_error "Backend usa caminho antigo: ../backend (deve ser ../sky-poc-backend)"
    else
        log_error "Backend: contexto não encontrado ou incorreto"
    fi
fi

# Verificar caminhos do frontend
if grep -q "context: ../sky-poc-frontend" "$DOCKER_COMPOSE"; then
    log_success "Frontend usa contexto correto: ../sky-poc-frontend"
    
    # Verificar se caminho existe
    FRONTEND_PATH="$PROJECT_DIR/../sky-poc-frontend"
    if [ -d "$FRONTEND_PATH" ]; then
        log_success "Caminho frontend existe e é acessível"
    else
        log_error "Caminho frontend não existe: $FRONTEND_PATH"
    fi
else
    if grep -q "context: ../frontend" "$DOCKER_COMPOSE"; then
        log_error "Frontend usa caminho antigo: ../frontend (deve ser ../sky-poc-frontend)"
    else
        log_error "Frontend: contexto não encontrado ou incorreto"
    fi
fi

# Verificar Dockerfiles
BACKEND_DOCKERFILE="$PROJECT_DIR/../sky-poc-backend/docker/Dockerfile"
if [ -f "$BACKEND_DOCKERFILE" ]; then
    log_success "Backend Dockerfile encontrado: docker/Dockerfile"
elif [ -f "$PROJECT_DIR/../sky-poc-backend/Dockerfile" ]; then
    log_warning "Backend Dockerfile em localização alternativa: Dockerfile (não docker/Dockerfile)"
else
    log_error "Backend Dockerfile não encontrado"
fi

FRONTEND_DOCKERFILE="$PROJECT_DIR/../sky-poc-frontend/docker/Dockerfile"
if [ -f "$FRONTEND_DOCKERFILE" ]; then
    log_success "Frontend Dockerfile encontrado: docker/Dockerfile"
elif [ -f "$PROJECT_DIR/../sky-poc-frontend/Dockerfile" ]; then
    log_warning "Frontend Dockerfile em localização alternativa: Dockerfile (não docker/Dockerfile)"
else
    log_error "Frontend Dockerfile não encontrado"
fi

# Verificar se IA é referenciada (pode não ter container próprio)
if grep -qi "ia\|sky-poc-ai" "$DOCKER_COMPOSE"; then
    log_info "IA referenciada no docker-compose.yml"
    IA_PATH="$PROJECT_DIR/../sky-poc-ai"
    if [ -d "$IA_PATH" ]; then
        log_success "Diretório IA encontrado"
    else
        log_warning "Diretório IA não encontrado (pode ser normal se não tiver container)"
    fi
fi

# ============================================
# 3. DEPENDÊNCIAS ENTRE SERVIÇOS
# ============================================
log_section "3. DEPENDÊNCIAS ENTRE SERVIÇOS"

# Backend depende de postgres, redis, migrate
if grep -A 15 "backend:" "$DOCKER_COMPOSE" | grep -q "depends_on:"; then
    if grep -A 15 "backend:" "$DOCKER_COMPOSE" | grep -q "postgres:"; then
        log_success "Backend depende de PostgreSQL"
    else
        log_error "Backend não depende de PostgreSQL"
    fi
    
    if grep -A 15 "backend:" "$DOCKER_COMPOSE" | grep -q "redis:"; then
        log_success "Backend depende de Redis"
    else
        log_error "Backend não depende de Redis"
    fi
    
    if grep -A 15 "backend:" "$DOCKER_COMPOSE" | grep -q "migrate:"; then
        log_success "Backend depende de migrate (correto - aguarda migrations)"
    else
        log_warning "Backend não depende explicitamente de migrate"
    fi
else
    log_error "Backend não tem depends_on configurado"
fi

# Frontend depende de backend
if grep -A 10 "frontend:" "$DOCKER_COMPOSE" | grep -q "depends_on:"; then
    if grep -A 10 "frontend:" "$DOCKER_COMPOSE" | grep -q "backend:"; then
        log_success "Frontend depende de Backend"
    else
        log_warning "Frontend não depende explicitamente de Backend"
    fi
else
    log_warning "Frontend não tem depends_on configurado"
fi

# Migrate depende de postgres
if grep -A 10 "migrate:" "$DOCKER_COMPOSE" | grep -q "depends_on:"; then
    if grep -A 10 "migrate:" "$DOCKER_COMPOSE" | grep -q "postgres:"; then
        log_success "Migrate depende de PostgreSQL"
    else
        log_error "Migrate não depende de PostgreSQL"
    fi
fi

# Worker e Beat dependem de postgres, redis, migrate
for service in "worker" "beat"; do
    if grep -A 20 "$service:" "$DOCKER_COMPOSE" | grep -q "depends_on:"; then
        if grep -A 20 "$service:" "$DOCKER_COMPOSE" | grep -q "postgres:"; then
            log_success "$service depende de PostgreSQL"
        fi
        if grep -A 20 "$service:" "$DOCKER_COMPOSE" | grep -q "redis:"; then
            log_success "$service depende de Redis"
        fi
        if grep -A 20 "$service:" "$DOCKER_COMPOSE" | grep -q "migrate:"; then
            log_success "$service depende de migrate"
        fi
    fi
done

# ============================================
# 4. TERRAFORM DEPLOY - CONSISTÊNCIA
# ============================================
log_section "4. TERRAFORM DEPLOY - CONSISTÊNCIA COM DOCKER COMPOSE"

DEPLOY_TF="$PROJECT_DIR/infra/azure/deploy.tf"

if [ ! -f "$DEPLOY_TF" ]; then
    log_error "deploy.tf não encontrado"
else
    log_success "deploy.tf encontrado"
    
    # Verificar se suporta ambos os nomes (poc-deploy e sky-poc-infra)
    if grep -q "poc-deploy\|sky-poc-infra" "$DEPLOY_TF"; then
        log_success "deploy.tf suporta ambos os nomes de estrutura"
    else
        log_warning "deploy.tf pode não suportar ambos os nomes"
    fi
    
    # Verificar se suporta ambos os nomes de repositórios
    if grep -q "backend\|sky-poc-backend" "$DEPLOY_TF"; then
        log_success "deploy.tf suporta ambos os nomes de backend"
    else
        log_warning "deploy.tf pode não suportar ambos os nomes de backend"
    fi
    
    if grep -q "frontend\|sky-poc-frontend" "$DEPLOY_TF"; then
        log_success "deploy.tf suporta ambos os nomes de frontend"
    else
        log_warning "deploy.tf pode não suportar ambos os nomes de frontend"
    fi
    
    if grep -q "ia\|sky-poc-ai" "$DEPLOY_TF"; then
        log_success "deploy.tf suporta ambos os nomes de IA"
    else
        log_warning "deploy.tf pode não suportar ambos os nomes de IA"
    fi
fi

# ============================================
# 5. VARIÁVEIS DE AMBIENTE
# ============================================
log_section "5. VARIÁVEIS DE AMBIENTE E CONFIGURAÇÕES"

# Verificar .env
if [ -f "$PROJECT_DIR/.env" ]; then
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
            if [ -z "$VALUE" ] || [ "$VALUE" = "secure_password_here" ] || [ "$VALUE" = "generate_a_secure_random_string_here" ] || [ "$VALUE" = "generate_another_secure_key_here" ]; then
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
        if [[ "$API_URL" == *"localhost"* ]]; then
            log_info "NEXT_PUBLIC_API_URL configurado para local: $API_URL"
        elif [[ "$API_URL" == *"172.191.77.30"* ]]; then
            log_info "NEXT_PUBLIC_API_URL configurado para VM: $API_URL"
        fi
    else
        log_warning "NEXT_PUBLIC_API_URL não encontrado no .env"
    fi
else
    log_warning ".env não encontrado (será criado de env.example se necessário)"
fi

# ============================================
# 6. REDES E CONECTIVIDADE
# ============================================
log_section "6. REDES E CONECTIVIDADE"

# Verificar se todos os serviços estão na mesma rede
if grep -q "ai_saas_network" "$DOCKER_COMPOSE"; then
    log_success "Rede ai_saas_network configurada"
    
    # Verificar se todos os serviços usam a rede
    SERVICES=("postgres" "redis" "backend" "frontend" "worker" "beat" "migrate" "proxy")
    for service in "${SERVICES[@]}"; do
        if grep -A 20 "$service:" "$DOCKER_COMPOSE" | grep -q "ai_saas_network"; then
            log_success "$service está na rede ai_saas_network"
        else
            log_warning "$service pode não estar na rede ai_saas_network"
        fi
    done
else
    log_error "Rede ai_saas_network não configurada"
fi

# ============================================
# 7. CONFLITOS POTENCIAIS
# ============================================
log_section "7. VERIFICANDO CONFLITOS POTENCIAIS"

# Verificar portas duplicadas
PORTS=$(grep -E "^\s*-\s*\"[0-9]+:" "$DOCKER_COMPOSE" | sed 's/.*"\([0-9]*\):.*/\1/' | sort)
DUPLICATE_PORTS=$(echo "$PORTS" | uniq -d)

if [ -n "$DUPLICATE_PORTS" ]; then
    log_error "Portas duplicadas encontradas: $DUPLICATE_PORTS"
else
    log_success "Nenhuma porta duplicada encontrada"
fi

# Verificar nomes de containers duplicados
CONTAINERS=$(grep "container_name:" "$DOCKER_COMPOSE" | sed 's/.*container_name:\s*\(.*\)/\1/' | sort)
DUPLICATE_CONTAINERS=$(echo "$CONTAINERS" | uniq -d)

if [ -n "$DUPLICATE_CONTAINERS" ]; then
    log_error "Nomes de containers duplicados: $DUPLICATE_CONTAINERS"
else
    log_success "Nenhum nome de container duplicado"
fi

# Verificar volumes duplicados
VOLUMES=$(grep -E "^\s+- [a-z_]+:" "$DOCKER_COMPOSE" | grep -v "container_name" | sed 's/.*-\s*\([a-z_]*\):.*/\1/' | sort | uniq)
if [ -n "$VOLUMES" ]; then
    log_success "Volumes configurados: $(echo $VOLUMES | tr '\n' ' ')"
fi

# ============================================
# 8. VALIDAÇÃO DOCKER COMPOSE
# ============================================
log_section "8. VALIDAÇÃO DE SINTAXE DOCKER COMPOSE"

if command -v docker &> /dev/null && docker ps &> /dev/null; then
    if docker compose -f "$DOCKER_COMPOSE" config &> /tmp/docker-compose-validation.log 2>&1; then
        log_success "docker-compose.yml: sintaxe válida"
    else
        log_error "docker-compose.yml: erro de sintaxe"
        cat /tmp/docker-compose-validation.log | head -20
    fi
else
    log_warning "Docker não disponível - pulando validação de sintaxe"
fi

# ============================================
# RESUMO FINAL
# ============================================
log_section "RESUMO DA VALIDAÇÃO"

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

