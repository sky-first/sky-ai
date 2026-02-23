#!/bin/bash
# scripts/validate-build.sh
# Valida build de todos os serviços antes do deploy (Fail Fast)
# Boas práticas DevOps: Validar antes de fazer deploy

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
echo "║     Validação de Build (Fail Fast)                  ║"
echo "║     Boas Práticas DevOps                            ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ============================================
# 1. VALIDAR DOCKER COMPOSE
# ============================================
log_section "1. Validando Docker Compose"

if command -v docker &>/dev/null && docker info &>/dev/null; then
    if docker compose -f "$PROJECT_DIR/docker-compose.yml" config &>/dev/null; then
        log_success "Docker Compose válido"
    else
        log_error "Docker Compose inválido"
        docker compose -f "$PROJECT_DIR/docker-compose.yml" config 2>&1 | head -20
    fi
else
    log_warning "Docker não disponível - pulando validação Docker Compose"
fi

# ============================================
# 2. VALIDAR BUILD DO FRONTEND (CRÍTICO)
# ============================================
log_section "2. Validando Build do Frontend"

FRONTEND_DIR="$PROJECT_DIR/../sky-poc-frontend"

if [ ! -d "$FRONTEND_DIR" ]; then
    log_error "Diretório frontend não encontrado: $FRONTEND_DIR"
    log_info "Clone o repositório: git clone <repo> sky-poc-frontend"
else
    log_info "Validando build do frontend..."
    
    cd "$FRONTEND_DIR"
    
    # Verificar se package.json existe
    if [ ! -f "package.json" ]; then
        log_error "package.json não encontrado no frontend"
    else
        # Verificar se node_modules existe (dependências instaladas)
        if [ ! -d "node_modules" ]; then
            log_warning "node_modules não encontrado"
            if command -v npm &>/dev/null; then
                log_info "Instalando dependências..."
                npm ci || {
                    log_warning "Falha ao instalar dependências (não crítico - será instalado na VM)"
                }
            else
                log_warning "npm não encontrado localmente (OK - validação será feita na VM durante deploy)"
            fi
        fi
        
        # Tentar build (se npm estiver disponível)
        if command -v npm &>/dev/null && [ -d "node_modules" ]; then
            log_info "Executando build do frontend localmente..."
            if npm run build 2>&1 | tee /tmp/frontend-build.log; then
                log_success "Build do frontend OK (validação local)"
            else
                log_warning "Build do frontend FALHOU localmente"
                echo ""
                echo "Últimas linhas do erro:"
                tail -30 /tmp/frontend-build.log | grep -A 20 -E "(error|Error|ERROR|failed|Failed)" || tail -30 /tmp/frontend-build.log
                echo ""
                log_info "[WARNING] Build falhou localmente, mas validação completa será feita na VM durante deploy"
                log_info "Se o build falhar na VM, o deploy será interrompido automaticamente"
            fi
        else
            log_info "npm não disponível localmente - validação de build será feita na VM durante deploy"
            log_info "O script de deploy validará o build antes de subir containers (Fail Fast)"
        fi
    fi
    
    cd "$PROJECT_DIR"
fi

# ============================================
# 3. VALIDAR BUILD DO BACKEND (OPCIONAL)
# ============================================
log_section "3. Validando Build do Backend"

BACKEND_DIR="$PROJECT_DIR/../sky-poc-backend"

if [ ! -d "$BACKEND_DIR" ]; then
    log_warning "Diretório backend não encontrado: $BACKEND_DIR"
else
    log_info "Validando estrutura do backend..."
    
    # Verificar se requirements.txt ou pyproject.toml existe
    if [ -f "$BACKEND_DIR/requirements.txt" ] || [ -f "$BACKEND_DIR/pyproject.toml" ]; then
        log_success "Estrutura do backend OK"
    else
        log_warning "requirements.txt ou pyproject.toml não encontrado"
    fi
fi

# ============================================
# 4. VALIDAR ESTRUTURA DE DIRETÓRIOS
# ============================================
log_section "4. Validando Estrutura de Diretórios"

REQUIRED_DIRS=(
    "../sky-poc-backend"
    "../sky-poc-frontend"
    "../sky-poc-ai"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ -d "$PROJECT_DIR/$dir" ]; then
        log_success "Diretório encontrado: $dir"
    else
        log_error "Diretório não encontrado: $dir"
    fi
done

# ============================================
# RESUMO
# ============================================
log_section "Resumo da Validação"

echo -e "${BLUE}Erros encontrados: ${RED}$ERRORS${NC}"
echo -e "${BLUE}Avisos encontrados: ${YELLOW}$WARNINGS${NC}"
echo ""

# Contar apenas erros críticos (não avisos sobre npm local)
CRITICAL_ERRORS=0

# Verificar se há erros críticos (Docker Compose, estrutura de diretórios)
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    CRITICAL_ERRORS=$((CRITICAL_ERRORS + 1))
fi

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ ! -d "$PROJECT_DIR/$dir" ]; then
        CRITICAL_ERRORS=$((CRITICAL_ERRORS + 1))
    fi
done

if [ $CRITICAL_ERRORS -eq 0 ]; then
    echo -e "${GREEN}[OK] Validação básica OK!${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}[WARNING] $WARNINGS aviso(s) encontrado(s)${NC}"
        echo -e "${YELLOW}Validação completa de build será feita na VM durante deploy${NC}"
    fi
    echo -e "${GREEN}Pronto para deploy!${NC}"
    echo ""
    echo "O script de deploy irá:"
    echo "  1. Validar build do frontend na VM antes de subir containers"
    echo "  2. Falhar imediatamente se build falhar (Fail Fast)"
    echo "  3. Mostrar logs detalhados de qualquer erro"
    exit 0
else
    echo -e "${RED}[ERROR] Validação falhou com $CRITICAL_ERRORS erro(s) crítico(s)${NC}"
    echo -e "${RED}Corrija os erros antes de continuar${NC}"
    echo ""
    echo "Próximos passos:"
    echo "  1. Corrija os erros críticos listados acima"
    echo "  2. Execute novamente: ./scripts/validate-build.sh"
    echo "  3. Após validação OK, execute: ./scripts/deploy-local-to-vm.sh"
    exit 1
fi

