#!/bin/bash
# Script de validação de configuração .env
# Valida variáveis obrigatórias, formatos e valores antes do deploy
# Uso: ./scripts/validate-env.sh [caminho-do-.env]

set -eu

ENV_FILE="${1:-.env}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE_PATH="$PROJECT_DIR/$ENV_FILE"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Função para log de erro
log_error() {
    echo -e "${RED}[ERROR] ERRO:${NC} $1" >&2
    ((ERRORS++))
}

# Função para log de aviso
log_warning() {
    echo -e "${YELLOW}[WARNING] AVISO:${NC} $1"
    ((WARNINGS++))
}

# Função para log de sucesso
log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

# Função para validar formato de URL
validate_url() {
    local url="$1"
    if [[ ! "$url" =~ ^https?://[a-zA-Z0-9.-]+(:[0-9]+)?(/.*)?$ ]]; then
        return 1
    fi
    return 0
}

# Função para validar formato de IP
validate_ip() {
    local ip="$1"
    if [[ ! "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(:[0-9]+)?$ ]]; then
        return 1
    fi
    return 0
}

# Função para validar se variável existe e não está vazia
check_required() {
    local var_name="$1"
    local var_value="${!var_name:-}"
    
    if [ -z "$var_value" ]; then
        log_error "Variável obrigatória não definida: $var_name"
        return 1
    fi
    
    log_success "$var_name está definida"
    return 0
}

# Função para validar formato de DATABASE_URL
validate_database_url() {
    local db_url="$1"
    
    if [ -z "$db_url" ]; then
        log_error "DATABASE_URL não pode estar vazia"
        return 1
    fi
    
    # Verificar se usa asyncpg (obrigatório)
    if [[ ! "$db_url" =~ postgresql\+asyncpg:// ]]; then
        log_error "DATABASE_URL deve usar 'postgresql+asyncpg://' (driver assíncrono)"
        return 1
    fi
    
    # Verificar se não tem sslmode=require (Postgres interno não usa SSL)
    if [[ "$db_url" =~ sslmode=require ]]; then
        log_error "DATABASE_URL não deve ter '?sslmode=require' (Postgres interno não usa SSL)"
        return 1
    fi
    
    # Verificar formato básico (permite query params opcionais, mas não sslmode=require)
    if [[ ! "$db_url" =~ ^postgresql\+asyncpg://[^:]+:[^@]+@[^:]+:[0-9]+/[^?]*(\?[^=]+=[^&]+(&[^=]+=[^&]+)*)?$ ]]; then
        log_warning "DATABASE_URL pode ter formato inválido: $db_url"
    fi
    
    log_success "DATABASE_URL válida"
    return 0
}

# Função para validar CORS_ORIGINS
validate_cors_origins() {
    local cors="$1"
    
    if [ -z "$cors" ]; then
        log_warning "CORS_ORIGINS não definida (usando padrão)"
        return 0
    fi
    
    # Verificar se não usa "*" ou "0.0.0.0" (vulnerabilidade)
    if [[ "$cors" =~ \* ]] || [[ "$cors" =~ 0\.0\.0\.0 ]]; then
        log_error "CORS_ORIGINS não pode conter '*' ou '0.0.0.0' (vulnerabilidade de segurança)"
        return 1
    fi
    
    # Validar cada origem na lista
    IFS=',' read -ra ORIGINS <<< "$cors"
    for origin in "${ORIGINS[@]}"; do
        origin=$(echo "$origin" | xargs) # trim
        if ! validate_url "$origin" && ! validate_ip "$origin"; then
            log_warning "Origem CORS pode ter formato inválido: $origin"
        fi
    done
    
    log_success "CORS_ORIGINS válida"
    return 0
}

# Função para validar senha forte
validate_password() {
    local password="$1"
    local var_name="$2"
    
    if [ -z "$password" ]; then
        log_error "$var_name não pode estar vazia"
        return 1
    fi
    
    if [ ${#password} -lt 12 ]; then
        log_warning "$var_name muito curta (mínimo 12 caracteres recomendado)"
    fi
    
    if [[ ! "$password" =~ [A-Z] ]] || [[ ! "$password" =~ [a-z] ]] || [[ ! "$password" =~ [0-9] ]]; then
        log_warning "$var_name deve conter maiúsculas, minúsculas e números (recomendado)"
    fi
    
    return 0
}

# Função para validar NEXT_PUBLIC_API_URL
validate_next_public_api_url() {
    local api_url="$1"
    
    if [ -z "$api_url" ]; then
        log_warning "NEXT_PUBLIC_API_URL não definida (usando padrão)"
        return 0
    fi
    
    # Verificar se termina com /api/v1
    if [[ ! "$api_url" =~ /api/v1$ ]]; then
        log_warning "NEXT_PUBLIC_API_URL deve terminar com '/api/v1'"
    fi
    
    if ! validate_url "$api_url"; then
        log_error "NEXT_PUBLIC_API_URL tem formato inválido: $api_url"
        return 1
    fi
    
    log_success "NEXT_PUBLIC_API_URL válida"
    return 0
}

echo "=========================================="
echo "🔍 Validação de Configuração .env"
echo "=========================================="
echo ""
echo "Arquivo: $ENV_FILE_PATH"
echo ""

# Verificar se arquivo existe
if [ ! -f "$ENV_FILE_PATH" ]; then
    log_error "Arquivo .env não encontrado: $ENV_FILE_PATH"
    echo ""
    echo "Crie o arquivo .env a partir de env.example:"
    echo "  cp env.example .env"
    exit 1
fi

log_success "Arquivo .env encontrado"
echo ""

# Carregar variáveis do .env
set -a
source "$ENV_FILE_PATH" 2>/dev/null || {
    log_error "Erro ao carregar arquivo .env"
    exit 1
}
set +a

echo "=========================================="
echo "📋 Validando Variáveis Obrigatórias"
echo "=========================================="
echo ""

# Variáveis obrigatórias
REQUIRED_VARS=(
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
    "POSTGRES_DB"
    "REDIS_PASSWORD"
    "JWT_SECRET_KEY"
    "ENCRYPTION_KEY"
    "DATABASE_URL"
)

for var in "${REQUIRED_VARS[@]}"; do
    check_required "$var" || true
done

echo ""
echo "=========================================="
echo "🔐 Validando Segurança"
echo "=========================================="
echo ""

# Validar senhas
validate_password "${POSTGRES_PASSWORD:-}" "POSTGRES_PASSWORD" || true
validate_password "${REDIS_PASSWORD:-}" "REDIS_PASSWORD" || true
validate_password "${JWT_SECRET_KEY:-}" "JWT_SECRET_KEY" || true
validate_password "${ENCRYPTION_KEY:-}" "ENCRYPTION_KEY" || true

echo ""
echo "=========================================="
echo "🔗 Validando URLs e Conexões"
echo "=========================================="
echo ""

# Validar DATABASE_URL
if [ -n "${DATABASE_URL:-}" ]; then
    validate_database_url "$DATABASE_URL" || true
fi

# Validar NEXT_PUBLIC_API_URL
if [ -n "${NEXT_PUBLIC_API_URL:-}" ]; then
    validate_next_public_api_url "$NEXT_PUBLIC_API_URL" || true
fi

# Validar CORS_ORIGINS
if [ -n "${CORS_ORIGINS:-}" ]; then
    validate_cors_origins "$CORS_ORIGINS" || true
fi

echo ""
echo "=========================================="
echo "📊 Resumo da Validação"
echo "=========================================="
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}[OK] Todas as validações passaram!${NC}"
    echo ""
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}[WARNING] Validação concluída com $WARNINGS aviso(s)${NC}"
    echo -e "${GREEN}[OK] Nenhum erro crítico encontrado${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}[ERROR] Validação falhou com $ERRORS erro(s) e $WARNINGS aviso(s)${NC}"
    echo ""
    echo "Corrija os erros antes de continuar com o deploy."
    exit 1
fi

