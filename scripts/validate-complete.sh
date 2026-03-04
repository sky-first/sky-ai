#!/bin/bash
# scripts/validate-complete.sh
# Validação completa e minuciosa antes do deploy local
# Revisa: estrutura, docker compose, variáveis, health checks, configurações

set -eu

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
log_section() { echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${CYAN} $1${NC}"; echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════╗"
echo "║     Validação Completa Pré-Deploy                 ║"
echo "║     Revisão Minuciosa de Especialista              ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ============================================
# 1. ESTRUTURA DE PASTAS
# ============================================
log_section "1. Validando Estrutura de Pastas"

if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    log_error "docker-compose.yml não encontrado"
    exit 1
fi
log_success "docker-compose.yml encontrado"

# Verificar repositórios
REQUIRED_DIRS=(
    "../sky-poc-backend"
    "../sky-poc-frontend"
    "../sky-poc-ai"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    full_path="$PROJECT_DIR/$dir"
    if [ ! -d "$full_path" ]; then
        log_error "$dir não encontrado"
    else
        log_success "$dir encontrado"
    fi
done

# ============================================
# 2. DOCKER E DOCKER COMPOSE
# ============================================
log_section "2. Validando Docker e Docker Compose"

if ! command -v docker &> /dev/null; then
    log_error "Docker não está instalado"
else
    DOCKER_VERSION=$(docker --version)
    log_success "Docker instalado: $DOCKER_VERSION"
fi

if ! docker ps &> /dev/null; then
    log_error "Docker não está rodando ou sem permissão"
else
    log_success "Docker está rodando"
fi

if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
    log_error "Docker Compose não está instalado"
else
    log_success "Docker Compose instalado"
fi

# ============================================
# 3. VALIDAÇÃO DOCKER COMPOSE
# ============================================
log_section "3. Validando Docker Compose (Sintaxe)"

if docker compose -f "$PROJECT_DIR/docker-compose.yml" config &> /tmp/docker-compose-validation.log; then
    log_success "docker-compose.yml: sintaxe válida"
else
    log_error "docker-compose.yml: erro de sintaxe"
    cat /tmp/docker-compose-validation.log
fi

if docker compose -f "$PROJECT_DIR/docker-compose.infrastructure.yml" config &> /tmp/docker-compose-infra-validation.log; then
    log_success "docker-compose.infrastructure.yml: sintaxe válida"
else
    log_error "docker-compose.infrastructure.yml: erro de sintaxe"
    cat /tmp/docker-compose-infra-validation.log
fi

# ============================================
# 4. CAMINHOS E CONTEXTOS
# ============================================
log_section "4. Validando Caminhos e Contextos"

# Verificar contextos no docker-compose.yml
if grep -q "context: ../backend[^/]" "$PROJECT_DIR/docker-compose.yml"; then
    log_error "docker-compose.yml usa 'context: ../backend' (deve ser ../sky-poc-backend)"
fi

if grep -q "context: ../frontend[^/]" "$PROJECT_DIR/docker-compose.yml"; then
    log_error "docker-compose.yml usa 'context: ../frontend' (deve ser ../sky-poc-frontend)"
fi

if grep -q "context: ../sky-poc-backend" "$PROJECT_DIR/docker-compose.yml"; then
    log_success "Backend usa contexto correto: ../sky-poc-backend"
fi

if grep -q "context: ../sky-poc-frontend" "$PROJECT_DIR/docker-compose.yml"; then
    log_success "Frontend usa contexto correto: ../sky-poc-frontend"
fi

# Verificar se os diretórios de build existem
BACKEND_CONTEXT=$(grep -A 1 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep "context:" | awk '{print $2}' | head -1)
if [ -n "$BACKEND_CONTEXT" ]; then
    BACKEND_FULL="$PROJECT_DIR/$BACKEND_CONTEXT"
    if [ -d "$BACKEND_FULL" ]; then
        log_success "Contexto backend existe: $BACKEND_CONTEXT"
    else
        log_error "Contexto backend não existe: $BACKEND_CONTEXT"
    fi
fi

# ============================================
# 5. HEALTH CHECKS
# ============================================
log_section "5. Validando Health Checks"

# Redis health check deve usar senha
if grep -q "redis-cli.*ping" "$PROJECT_DIR/docker-compose.yml" && ! grep -q "REDIS_PASSWORD" "$PROJECT_DIR/docker-compose.yml" | grep -A 2 "healthcheck"; then
    if grep -q "redis-cli -a" "$PROJECT_DIR/docker-compose.yml"; then
        log_success "Redis health check usa senha"
    else
        log_warning "Redis health check pode não funcionar (falta senha)"
    fi
fi

# PostgreSQL health check
if grep -q "pg_isready" "$PROJECT_DIR/docker-compose.yml"; then
    log_success "PostgreSQL health check configurado"
fi

# Backend health check
if grep -q "healthcheck" "$PROJECT_DIR/docker-compose.yml" | grep -A 3 "backend:"; then
    log_success "Backend health check configurado"
fi

# ============================================
# 6. VARIÁVEIS DE AMBIENTE
# ============================================
log_section "6. Validando Variáveis de Ambiente"

if [ ! -f "$PROJECT_DIR/.env" ]; then
    log_warning ".env não encontrado (será criado de env.example)"
    if [ ! -f "$PROJECT_DIR/env.example" ]; then
        log_error "env.example não encontrado"
    fi
else
    log_success ".env encontrado"
    
    # Verificar placeholders
    if grep -q "secure_password_here\|generate_a_secure\|generate_another" "$PROJECT_DIR/.env"; then
        log_warning ".env contém valores placeholder (deve gerar valores reais)"
    else
        log_success ".env não contém placeholders"
    fi
    
    # Verificar variáveis obrigatórias
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
            log_success "NEXT_PUBLIC_API_URL configurado para local: $API_URL"
        elif [[ "$API_URL" == *"172.191.77.30"* ]]; then
            log_warning "NEXT_PUBLIC_API_URL aponta para VM (ok para produção, mas para local use localhost)"
        fi
    fi
fi

# ============================================
# 7. NGINX CONFIGURATION
# ============================================
log_section "7. Validando Configuração Nginx"

if [ -f "$PROJECT_DIR/docker/nginx/nginx.conf" ]; then
    log_success "nginx.conf encontrado"
    
    # Verificar se HTTPS está forçado sem certificados
    if grep -q "return 301 https" "$PROJECT_DIR/docker/nginx/nginx.conf" && ! grep -q "#.*return 301 https" "$PROJECT_DIR/docker/nginx/nginx.conf"; then
        log_warning "Nginx força HTTPS mas certificados podem não estar configurados"
    else
        log_success "Nginx configurado corretamente (HTTP ou HTTPS comentado)"
    fi
else
    log_warning "nginx.conf não encontrado (pode ser normal se não usar nginx)"
fi

# ============================================
# 8. DEPENDÊNCIAS
# ============================================
log_section "8. Validando Dependências entre Serviços"

# Backend depende de postgres, redis, migrate
if grep -A 10 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "depends_on:"; then
    if grep -A 15 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "postgres:"; then
        log_success "Backend depende de PostgreSQL"
    fi
    if grep -A 15 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "redis:"; then
        log_success "Backend depende de Redis"
    fi
    if grep -A 15 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "migrate:"; then
        log_success "Backend depende de migrate"
    fi
fi

# Frontend depende de backend
if grep -A 5 "frontend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "depends_on:"; then
    if grep -A 10 "frontend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "backend:"; then
        log_success "Frontend depende de Backend"
    fi
fi

# ============================================
# 9. VOLUMES E PERSISTÊNCIA
# ============================================
log_section "9. Validando Volumes e Persistência"

if grep -q "postgres_data:" "$PROJECT_DIR/docker-compose.yml"; then
    log_success "Volume PostgreSQL configurado"
fi

if grep -q "redis_data:" "$PROJECT_DIR/docker-compose.yml"; then
    log_success "Volume Redis configurado"
fi

# ============================================
# 10. REDES
# ============================================
log_section "10. Validando Redes"

if grep -q "ai_saas_network:" "$PROJECT_DIR/docker-compose.yml"; then
    log_success "Rede ai_saas_network configurada"
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
    echo -e "${GREEN}Pronto para deploy local!${NC}"
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

