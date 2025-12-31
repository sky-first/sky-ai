#!/bin/bash
# scripts/test-local-deploy.sh
# Validação completa local antes de testar na VM
# Simula o que o GitHub Actions fará
# Baseado no Checklist 100% deploy funcionando

set -euo pipefail

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
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; WARNINGS=$((WARNINGS + 1)); }
log_error() { echo -e "${RED}[✗]${NC} $1"; ERRORS=$((ERRORS + 1)); }
log_section() { echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${CYAN}▶ $1${NC}"; echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════╗"
echo "║     Teste Local - Checklist Completo               ║"
echo "║     Validação Pré-Deploy (Fase 1)                  ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ============================================
# 1. ACESSO AOS REPOSITÓRIOS
# ============================================
log_section "1. Validando Acesso aos Repositórios (Checklist Item 1)"

REPOS=(
    "sky-first/sky-poc-infra"
    "sky-first/sky-poc-backend"
    "sky-first/sky-poc-frontend"
    "sky-first/sky-poc-ai"
)

# Verificar se GH_PAT está configurado
HAS_PAT=false
HAS_TOKEN=false

if [ -n "${GH_PAT:-}" ]; then
    HAS_PAT=true
    log_info "GH_PAT configurado (recomendado)"
elif [ -n "${GITHUB_TOKEN:-}" ]; then
    HAS_TOKEN=true
    log_warning "Usando GITHUB_TOKEN (pode não ter acesso a repositórios privados)"
    log_info "Configure GH_PAT para acesso completo: export GH_PAT=seu_token"
else
    log_warning "Nenhum token configurado (testando acesso público)"
    log_info "Configure GH_PAT para acesso completo: export GH_PAT=seu_token"
fi

REPO_ACCESS_OK=true
for repo in "${REPOS[@]}"; do
    log_info "Verificando: $repo"
    
    # Tentar com autenticação se disponível
    if [ "$HAS_PAT" = true ]; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: token ${GH_PAT}" \
            "https://api.github.com/repos/${repo}" 2>/dev/null || echo "000")
        
        if [ "$HTTP_CODE" = "200" ]; then
            log_success "$repo: Acessível via PAT"
        elif [ "$HTTP_CODE" = "404" ]; then
            log_error "$repo: Não encontrado (404)"
            REPO_ACCESS_OK=false
        elif [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "403" ]; then
            log_error "$repo: Sem permissão (HTTP $HTTP_CODE)"
            REPO_ACCESS_OK=false
        else
            log_warning "$repo: Resposta inesperada (HTTP $HTTP_CODE)"
        fi
    elif [ "$HAS_TOKEN" = true ]; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: token ${GITHUB_TOKEN}" \
            "https://api.github.com/repos/${repo}" 2>/dev/null || echo "000")
        
        if [ "$HTTP_CODE" = "200" ]; then
            log_success "$repo: Acessível via GITHUB_TOKEN"
        elif [ "$HTTP_CODE" = "404" ]; then
            log_warning "$repo: Não encontrado (pode ser privado)"
        else
            log_warning "$repo: Resposta HTTP $HTTP_CODE"
        fi
    else
        # Teste público
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            "https://api.github.com/repos/${repo}" 2>/dev/null || echo "000")
        
        if [ "$HTTP_CODE" = "200" ]; then
            log_success "$repo: Acessível publicamente"
        else
            log_warning "$repo: Pode ser privado (configure GH_PAT)"
        fi
    fi
done

if [ "$REPO_ACCESS_OK" = false ]; then
    log_error "Alguns repositórios não estão acessíveis"
    log_info "SOLUÇÃO: Configure GH_PAT com permissão 'repo' para todos os 4 repositórios"
fi

# ============================================
# 2. SECRETS / .ENV
# ============================================
log_section "2. Validando Secrets / .env (Checklist Item 2)"

if [ ! -f "$PROJECT_DIR/.env" ]; then
    log_error ".env não encontrado"
    log_info "Copie de env.example: cp env.example .env"
    log_info "Ou execute: ./setup-local.sh"
else
    log_success ".env encontrado"
    
    # Verificar variáveis obrigatórias do checklist
    REQUIRED_VARS=(
        "POSTGRES_PASSWORD"
        "REDIS_PASSWORD"
        "JWT_SECRET_KEY"
        "ENCRYPTION_KEY"
        "CORS_ORIGINS"
        "NEXT_PUBLIC_API_URL"
    )
    
    MISSING_VARS=()
    PLACEHOLDER_VARS=()
    
    # Tentar ler .env com diferentes métodos
    if [ -r "$PROJECT_DIR/.env" ]; then
        ENV_CONTENT=$(cat "$PROJECT_DIR/.env" 2>/dev/null || echo "")
    else
        log_warning "Não foi possível ler .env (verifique permissões)"
        ENV_CONTENT=""
    fi
    
    for var in "${REQUIRED_VARS[@]}"; do
        if echo "$ENV_CONTENT" | grep -q "^${var}="; then
            VALUE=$(echo "$ENV_CONTENT" | grep "^${var}=" | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs)
            if [ -z "$VALUE" ] || \
               [[ "$VALUE" == *"secure_password"* ]] || \
               [[ "$VALUE" == *"generate"* ]] || \
               [[ "$VALUE" == *"here"* ]]; then
                log_warning "$var: Ainda tem placeholder"
                PLACEHOLDER_VARS+=("$var")
            else
                log_success "$var: Configurado"
            fi
        else
            log_error "$var: Não encontrado no .env"
            MISSING_VARS+=("$var")
        fi
    done
    
    if [ ${#MISSING_VARS[@]} -gt 0 ]; then
        log_error "Variáveis obrigatórias faltando: ${MISSING_VARS[*]}"
    fi
    
    if [ ${#PLACEHOLDER_VARS[@]} -gt 0 ]; then
        log_warning "Variáveis com placeholder: ${PLACEHOLDER_VARS[*]}"
        log_info "Gere valores seguros:"
        log_info "  POSTGRES_PASSWORD: openssl rand -base64 32"
        log_info "  REDIS_PASSWORD: openssl rand -base64 32"
        log_info "  JWT_SECRET_KEY: openssl rand -hex 32"
        log_info "  ENCRYPTION_KEY: openssl rand -hex 32"
    fi
    
    # Verificar permissões
    PERMS=$(stat -f "%A" "$PROJECT_DIR/.env" 2>/dev/null || stat -c "%a" "$PROJECT_DIR/.env" 2>/dev/null || echo "")
    if [ "$PERMS" != "600" ]; then
        log_warning ".env permissões: $PERMS (recomendado: 600)"
        log_info "Corrigir: chmod 600 .env"
    else
        log_success ".env permissões: 600"
    fi
fi

# ============================================
# 3. ESTRUTURA DE DIRETÓRIOS
# ============================================
log_section "3. Validando Estrutura de Diretórios (Checklist Item 3)"

REQUIRED_DIRS=(
    "../sky-poc-backend"
    "../sky-poc-frontend"
    "../sky-poc-ai"
)

DIRS_OK=true
for dir in "${REQUIRED_DIRS[@]}"; do
    full_path="$PROJECT_DIR/$dir"
    if [ ! -d "$full_path" ]; then
        log_error "$dir não encontrado"
        DIRS_OK=false
        log_info "Clone: git clone https://github.com/sky-first/${dir##*/}.git ../${dir##*/}"
    else
        log_success "$dir encontrado"
        
        # Verificar se é um repositório git
        if [ -d "$full_path/.git" ]; then
            log_success "$dir: É um repositório Git"
        else
            log_warning "$dir: Não é um repositório Git"
        fi
    fi
done

# Validar docker-compose.yml
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    log_error "docker-compose.yml não encontrado"
    DIRS_OK=false
else
    log_success "docker-compose.yml encontrado"
    
    # Verificar contexts (deve ser ../sky-poc-backend, não ../backend)
    if grep -q "context: ../sky-poc-backend" "$PROJECT_DIR/docker-compose.yml"; then
        log_success "Backend context correto: ../sky-poc-backend"
    elif grep -q "context: ../backend" "$PROJECT_DIR/docker-compose.yml"; then
        log_error "Backend context incorreto: ../backend (deve ser ../sky-poc-backend)"
        DIRS_OK=false
    else
        log_warning "Backend context não encontrado no docker-compose.yml"
    fi
    
    if grep -q "context: ../sky-poc-frontend" "$PROJECT_DIR/docker-compose.yml"; then
        log_success "Frontend context correto: ../sky-poc-frontend"
    elif grep -q "context: ../frontend" "$PROJECT_DIR/docker-compose.yml"; then
        log_error "Frontend context incorreto: ../frontend (deve ser ../sky-poc-frontend)"
        DIRS_OK=false
    fi
    
    if grep -q "context: ../sky-poc-ai" "$PROJECT_DIR/docker-compose.yml"; then
        log_success "AI context correto: ../sky-poc-ai"
    elif grep -q "context: ../ia" "$PROJECT_DIR/docker-compose.yml"; then
        log_warning "AI context usa ../ia (pode estar correto se houver symlink)"
    fi
fi

if [ "$DIRS_OK" = false ]; then
    log_error "Estrutura de diretórios incompleta"
fi

# ============================================
# 4. PRÉ-REQUISITOS
# ============================================
log_section "4. Validando Pré-requisitos (Checklist Item 4)"

# Docker
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version)
    log_success "Docker: $DOCKER_VERSION"
    
    if docker ps &> /dev/null 2>&1; then
        log_success "Docker está rodando"
    else
        # Verificar se é problema de permissão ou se Docker não está rodando
        if docker info &> /dev/null 2>&1; then
            log_success "Docker está rodando (info OK)"
        else
            log_warning "Docker não está rodando ou sem permissão"
            log_info "Inicie o Docker Desktop ou: sudo systemctl start docker"
            log_info "No macOS: Abra o Docker Desktop"
        fi
    fi
else
    log_error "Docker não instalado"
    log_info "Instale: https://www.docker.com/products/docker-desktop"
fi

# Docker Compose
if command -v docker compose &> /dev/null; then
    COMPOSE_VERSION=$(docker compose version 2>/dev/null || echo "unknown")
    log_success "Docker Compose: $COMPOSE_VERSION"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(docker-compose --version)
    log_success "Docker Compose (legacy): $COMPOSE_VERSION"
    log_warning "Recomendado usar 'docker compose' (plugin) ao invés de 'docker-compose'"
else
    log_error "Docker Compose não instalado"
fi

# Git
if command -v git &> /dev/null; then
    GIT_VERSION=$(git --version)
    log_success "Git: $GIT_VERSION"
    
    # Verificar configuração
    if git config --global user.name &> /dev/null && git config --global user.email &> /dev/null; then
        log_success "Git configurado: $(git config --global user.name) <$(git config --global user.email)>"
    else
        log_warning "Git não configurado (user.name e user.email)"
    fi
else
    log_error "Git não instalado"
fi

# ============================================
# 5. SCRIPTS COMPATÍVEIS COM RunShellScript
# ============================================
log_section "5. Validando Scripts (POSIX sh - Checklist Item 5)"

# Verificar scripts que serão usados na VM
SCRIPTS_TO_CHECK=(
    "scripts/validate-complete.sh"
    "scripts/health_check.sh"
    "scripts/azure/deploy_to_vm.sh"
)

for script in "${SCRIPTS_TO_CHECK[@]}"; do
    if [ -f "$PROJECT_DIR/$script" ]; then
        # Verificar se usa set -eu (sem pipefail) - compatível com RunShellScript
        if grep -q "set -eu" "$PROJECT_DIR/$script" || grep -q "set -euo" "$PROJECT_DIR/$script"; then
            log_success "$script: Usa set -eu (compatível com RunShellScript)"
        elif grep -q "set -e" "$PROJECT_DIR/$script"; then
            log_warning "$script: Usa set -e (recomendado set -eu)"
        else
            log_warning "$script: Não usa set -eu (pode ter problemas)"
        fi
        
        # Verificar se não usa pipefail (não suportado por RunShellScript)
        if grep -q "pipefail" "$PROJECT_DIR/$script"; then
            log_warning "$script: Usa pipefail (pode falhar no RunShellScript do Azure)"
        else
            log_success "$script: Não usa pipefail (compatível)"
        fi
        
        # Verificar se falha corretamente (exit 1, exit $VAR, exit $EXIT_CODE, etc)
        if grep -q "exit 1" "$PROJECT_DIR/$script" || \
           grep -q "exit [1-9]" "$PROJECT_DIR/$script" || \
           grep -q "exit \$" "$PROJECT_DIR/$script" || \
           grep -q "exit \${" "$PROJECT_DIR/$script"; then
            log_success "$script: Falha corretamente com exit code != 0"
        else
            log_warning "$script: Pode não falhar corretamente"
        fi
    else
        log_warning "$script: Não encontrado (pode não ser crítico)"
    fi
done

# ============================================
# 6. TERRAFORM STATE (se aplicável)
# ============================================
log_section "6. Validando Terraform (Checklist Item 6)"

if [ -d "$PROJECT_DIR/infra/azure" ]; then
    cd "$PROJECT_DIR/infra/azure"
    
    # Verificar arquivos tfvars
    TFVARS_FOUND=false
    for tfvars in terraform.tfvars.poc-sky terraform.tfvars.staging terraform.tfvars.prod; do
        if [ -f "$tfvars" ]; then
            log_success "Arquivo tfvars encontrado: $tfvars"
            TFVARS_FOUND=true
        fi
    done
    
    if [ "$TFVARS_FOUND" = false ]; then
        log_warning "Nenhum arquivo tfvars encontrado (terraform.tfvars.poc-sky, staging ou prod)"
    fi
    
    # Verificar se terraform está instalado
    if command -v terraform &> /dev/null 2>&1; then
        TERRAFORM_VERSION=$(terraform version -json 2>/dev/null | grep -o '"terraform_version":"[^"]*' | cut -d'"' -f4 2>/dev/null || terraform version 2>/dev/null | head -1 || echo "installed")
        log_success "Terraform: $TERRAFORM_VERSION"
        
        # Verificar se backend está configurado (se houver backend.hcl)
        if [ -f "backend.hcl" ]; then
            log_success "backend.hcl encontrado"
        else
            log_info "backend.hcl não encontrado (será criado pelo workflow)"
        fi
    else
        log_warning "Terraform não instalado (não crítico para teste local)"
    fi
    
    cd "$PROJECT_DIR"
else
    log_info "Diretório infra/azure não encontrado (não crítico para teste local)"
fi

# ============================================
# 7. DOCKER COMPOSE VALIDATION
# ============================================
log_section "7. Validando Docker Compose (Sintaxe e Contextos)"

if [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
    # Tentar validar sem ler .env (pode falhar se .env não estiver acessível)
    if docker compose -f "$PROJECT_DIR/docker-compose.yml" config > /dev/null 2>&1; then
        log_success "docker-compose.yml: Sintaxe válida"
        
        # Verificar se contexts existem
        CONTEXTS=$(docker compose -f "$PROJECT_DIR/docker-compose.yml" config 2>/dev/null | grep -A 1 "context:" | grep "context:" | awk '{print $2}' | tr -d '"' || true)
        if [ -n "$CONTEXTS" ]; then
            for context in $CONTEXTS; do
                # Resolver caminho relativo
                if [[ "$context" == ../* ]]; then
                    context_path="$PROJECT_DIR/$context"
                    if [ -d "$context_path" ]; then
                        log_success "Context existe: $context"
                    else
                        log_error "Context não existe: $context"
                    fi
                fi
            done
        fi
    else
        # Pode falhar por causa do .env, mas vamos tentar ver o erro
        ERROR_OUTPUT=$(docker compose -f "$PROJECT_DIR/docker-compose.yml" config 2>&1 || true)
        if echo "$ERROR_OUTPUT" | grep -q "operation not permitted\|Permission denied"; then
            log_warning "docker-compose.yml: Não foi possível validar (problema de permissão com .env)"
            log_info "Isso é normal se o .env não estiver acessível. Valide manualmente."
        elif echo "$ERROR_OUTPUT" | grep -q "syntax error\|parse error"; then
            log_error "docker-compose.yml: Erro de sintaxe"
            echo "$ERROR_OUTPUT" | head -20
        else
            log_warning "docker-compose.yml: Erro ao validar (pode ser por causa do .env)"
            log_info "Verifique manualmente: docker compose -f docker-compose.yml config"
        fi
    fi
else
    log_error "docker-compose.yml não encontrado"
fi

# ============================================
# 8. HEALTH CHECKS CONFIGURADOS
# ============================================
log_section "8. Validando Health Checks (Checklist Item 8)"

if [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
    # Verificar health check do Postgres
    if grep -q "pg_isready" "$PROJECT_DIR/docker-compose.yml"; then
        log_success "PostgreSQL health check configurado (pg_isready)"
    else
        log_warning "PostgreSQL health check não encontrado"
    fi
    
    # Verificar health check do Redis
    if grep -q "redis-cli.*ping" "$PROJECT_DIR/docker-compose.yml"; then
        if grep -q "redis-cli -a" "$PROJECT_DIR/docker-compose.yml" || grep -q "REDIS_PASSWORD" "$PROJECT_DIR/docker-compose.yml"; then
            log_success "Redis health check configurado (com senha)"
        else
            log_warning "Redis health check pode não funcionar (falta senha)"
        fi
    else
        log_warning "Redis health check não encontrado"
    fi
    
    # Verificar health check do Backend
    if grep -q "curl.*localhost:8000" "$PROJECT_DIR/docker-compose.yml" || \
       grep -A 15 "backend:" "$PROJECT_DIR/docker-compose.yml" | grep -q "healthcheck:"; then
        log_success "Backend health check configurado"
    else
        log_warning "Backend health check não encontrado"
    fi
fi

# ============================================
# RESUMO FINAL
# ============================================
log_section "Resumo da Validação"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Erros encontrados: ${RED}$ERRORS${NC}"
echo -e "${BLUE}Avisos encontrados: ${YELLOW}$WARNINGS${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅✅✅ VALIDAÇÃO COMPLETA: TUDO OK!${NC}"
    echo -e "${GREEN}Pronto para Fase 2: Deploy Local na VM${NC}"
    echo ""
    echo -e "${CYAN}Próximo passo:${NC}"
    echo "  ./scripts/deploy-local-to-vm.sh"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  VALIDAÇÃO OK com $WARNINGS aviso(s)${NC}"
    echo -e "${YELLOW}Recomendado revisar avisos antes de continuar${NC}"
    echo ""
    echo -e "${CYAN}Você pode continuar, mas é recomendado corrigir os avisos${NC}"
    exit 0
else
    echo -e "${RED}❌ VALIDAÇÃO FALHOU com $ERRORS erro(s)${NC}"
    echo -e "${RED}Corrija os erros antes de continuar${NC}"
    echo ""
    echo -e "${CYAN}Corrija os erros e execute novamente:${NC}"
    echo "  ./scripts/test-local-deploy.sh"
    exit 1
fi

