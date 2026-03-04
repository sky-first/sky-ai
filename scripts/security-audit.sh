#!/bin/bash
# scripts/security-audit.sh
# Auditoria completa de segurança SecOps/DevOps
# Verifica: secrets, network, containers, access control, compliance

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

CRITICAL=0
HIGH=0
MEDIUM=0
LOW=0
PASSED=0

log_critical() { echo -e "${RED}[CRITICAL]${NC} $1"; CRITICAL=$((CRITICAL + 1)); }
log_high() { echo -e "${MAGENTA}[HIGH]${NC} $1"; HIGH=$((HIGH + 1)); }
log_medium() { echo -e "${YELLOW}[MEDIUM]${NC} $1"; MEDIUM=$((MEDIUM + 1)); }
log_low() { echo -e "${BLUE}[LOW]${NC} $1"; LOW=$((LOW + 1)); }
log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; PASSED=$((PASSED + 1)); }
log_section() { 
    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; 
    echo -e "${CYAN} $1${NC}"; 
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; 
}

echo -e "${RED}"
echo "╔════════════════════════════════════════════════════╗"
echo "║     AUDITORIA DE SEGURANÇA SECOPS/DEVOPS          ║"
echo "║     Revisão Completa de Ponta a Ponta              ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ============================================
# 1. SECRETS MANAGEMENT
# ============================================
log_section "1. SECRETS MANAGEMENT"

# Verificar .env no .gitignore
if grep -q "^\.env$" "$PROJECT_DIR/.gitignore"; then
    log_pass ".env está no .gitignore"
else
    log_critical ".env NÃO está no .gitignore (risco de commit acidental)"
fi

# Verificar se .env está commitado
if git ls-files --error-unmatch .env &>/dev/null 2>&1; then
    log_critical ".env está sendo rastreado pelo git (REMOVER IMEDIATAMENTE)"
else
    log_pass ".env não está sendo rastreado pelo git"
fi

# Verificar hardcoded secrets
if grep -r -i "password.*=.*['\"][^'\"]\{8,\}" "$PROJECT_DIR" --include="*.tf" --include="*.yml" --include="*.yaml" --include="*.sh" 2>/dev/null | grep -v ".env" | grep -v "example" | grep -v "placeholder"; then
    log_high "Possíveis senhas hardcoded encontradas (revisar manualmente)"
else
    log_pass "Nenhuma senha hardcoded óbvia encontrada"
fi

# Verificar placeholders em arquivos de exemplo
if grep -q "secure_password_here\|generate_a_secure\|placeholder" "$PROJECT_DIR/env.example" 2>/dev/null; then
    log_pass "env.example usa placeholders (correto)"
else
    log_medium "env.example pode não ter placeholders claros"
fi

# Verificar uso de Key Vault
if grep -q "keyvault\|Key Vault" "$PROJECT_DIR/.github/workflows/deploy.yml" 2>/dev/null; then
    log_pass "Key Vault configurado no CI/CD"
else
    log_medium "Key Vault não detectado no CI/CD (recomendado para produção)"
fi

# Verificar permissões de arquivos sensíveis
if [ -f "$PROJECT_DIR/.env" ]; then
    PERMS=$(stat -c "%a" "$PROJECT_DIR/.env" 2>/dev/null || stat -f "%OLp" "$PROJECT_DIR/.env" 2>/dev/null || echo "000")
    if [[ "$PERMS" == "600" ]] || [[ "$PERMS" == "400" ]]; then
        log_pass ".env tem permissões restritas ($PERMS)"
    else
        log_high ".env tem permissões muito abertas ($PERMS) - deve ser 600"
    fi
fi

# ============================================
# 2. NETWORK SECURITY
# ============================================
log_section "2. NETWORK SECURITY"

# Verificar SSH público
if grep -q "allowed_ssh_ips.*=.*\[\"0.0.0.0/0\"\]" "$PROJECT_DIR/infra/azure/terraform.tfvars.prod" 2>/dev/null; then
    log_critical "SSH está aberto para 0.0.0.0/0 (TODO: Restringir para IPs específicos)"
else
    log_pass "SSH não está completamente aberto"
fi

# Verificar PostgreSQL público
if grep -q "allowed_postgres_ips.*=.*\[\"0.0.0.0/0\"\]" "$PROJECT_DIR/infra/azure/terraform.tfvars.prod" 2>/dev/null; then
    log_critical "PostgreSQL está aberto para 0.0.0.0/0 (CRÍTICO: deve ser apenas rede interna)"
else
    if grep -q "allowed_postgres_ips.*=.*\[\"10.0" "$PROJECT_DIR/infra/azure/terraform.tfvars.prod" 2>/dev/null; then
        log_pass "PostgreSQL restrito à rede interna"
    else
        log_medium "PostgreSQL: verificar configuração de acesso"
    fi
fi

# Verificar Backend público
if grep -q "backend_public_access.*=.*true" "$PROJECT_DIR/infra/azure/terraform.tfvars.prod" 2>/dev/null; then
    log_high "Backend está público (deve ser apenas via nginx interno)"
else
    log_pass "Backend não está público"
fi

# Verificar portas expostas no Docker
if grep -q "\"5432:5432\"" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_high "PostgreSQL expõe porta padrão 5432 (considerar usar porta não padrão)"
elif grep -q "5433:5432" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_pass "PostgreSQL usa porta não padrão (5433)"
fi

# Verificar Redis exposto
if grep -q "\"6379:6379\"" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_medium "Redis expõe porta 6379 (verificar se necessário para produção)"
else
    log_pass "Redis não expõe porta externamente"
fi

# Verificar CORS
if grep -q "CORS_ORIGINS.*0.0.0.0\|CORS_ORIGINS.*\*" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_high "CORS pode estar muito permissivo (verificar configuração)"
else
    log_pass "CORS parece configurado"
fi

# ============================================
# 3. CONTAINER SECURITY
# ============================================
log_section "3. CONTAINER SECURITY"

# Verificar se containers rodam como root
if grep -q "user:" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_pass "Containers especificam usuário não-root"
else
    log_high "Containers podem estar rodando como root (verificar Dockerfiles)"
fi

# Verificar read-only filesystems
if grep -q "read_only: true" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_pass "Alguns containers usam filesystem read-only"
else
    log_medium "Considerar filesystem read-only para containers (melhor prática)"
fi

# Verificar resource limits
if grep -q "mem_limit:" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_pass "Resource limits configurados"
else
    log_medium "Resource limits não configurados (recomendado)"
fi

# Verificar health checks
if grep -q "healthcheck:" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_pass "Health checks configurados"
else
    log_medium "Health checks não configurados para todos os serviços"
fi

# Verificar imagens com 'latest'
if grep -q ":latest" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_high "Algumas imagens usam tag 'latest' (usar versões específicas)"
else
    log_pass "Imagens não usam tag 'latest'"
fi

# Verificar se secrets estão em variáveis de ambiente
if grep -q "\${POSTGRES_PASSWORD}\|\${REDIS_PASSWORD}\|\${JWT_SECRET_KEY}" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_pass "Secrets usam variáveis de ambiente (não hardcoded)"
else
    log_critical "Secrets podem estar hardcoded no docker-compose.yml"
fi

# ============================================
# 4. ACCESS CONTROL
# ============================================
log_section "4. ACCESS CONTROL"

# Verificar SSH key authentication
if grep -q "disable_password_authentication.*=.*true" "$PROJECT_DIR/infra/azure"/*.tf 2>/dev/null; then
    log_pass "Autenticação por senha SSH desabilitada"
else
    log_high "Autenticação por senha SSH pode estar habilitada"
fi

# Verificar permissões de chaves SSH
if [ -d "$PROJECT_DIR/keys" ]; then
    for key in "$PROJECT_DIR/keys"/**/*.pem "$PROJECT_DIR/keys"/**/*.key "$PROJECT_DIR/keys"/**/id_rsa 2>/dev/null; do
        if [ -f "$key" ]; then
            PERMS=$(stat -c "%a" "$key" 2>/dev/null || stat -f "%OLp" "$key" 2>/dev/null || echo "000")
            if [[ "$PERMS" == "600" ]] || [[ "$PERMS" == "400" ]]; then
                log_pass "Chave SSH $key tem permissões corretas ($PERMS)"
            else
                log_high "Chave SSH $key tem permissões muito abertas ($PERMS)"
            fi
        fi
    done
fi

# Verificar .gitignore para chaves
if grep -q "keys/\*\*/id_rsa\|\.pem\|\.key" "$PROJECT_DIR/.gitignore" 2>/dev/null; then
    log_pass "Chaves privadas estão no .gitignore"
else
    log_high "Chaves privadas podem não estar no .gitignore"
fi

# ============================================
# 5. LOGGING & MONITORING
# ============================================
log_section "5. LOGGING & MONITORING"

# Verificar se logs estão configurados
if grep -q "logging:" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_pass "Logging configurado no Docker Compose"
else
    log_medium "Logging não configurado explicitamente (usar driver json-file ou syslog)"
fi

# Verificar Sentry
if grep -q "SENTRY_DSN" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_pass "Sentry configurado para error tracking"
else
    log_low "Sentry não configurado (recomendado para produção)"
fi

# ============================================
# 6. BACKUP & RECOVERY
# ============================================
log_section "6. BACKUP & RECOVERY"

# Verificar scripts de backup
if [ -f "$PROJECT_DIR/scripts/postgres/backup_volumes.sh" ] || [ -f "$PROJECT_DIR/scripts/backup"*.sh ]; then
    log_pass "Scripts de backup encontrados"
else
    log_medium "Scripts de backup não encontrados (recomendado)"
fi

# Verificar volumes persistentes
if grep -q "volumes:" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_pass "Volumes persistentes configurados"
else
    log_high "Volumes persistentes não configurados (risco de perda de dados)"
fi

# ============================================
# 7. COMPLIANCE & BEST PRACTICES
# ============================================
log_section "7. COMPLIANCE & BEST PRACTICES"

# Verificar DEBUG em produção
if grep -q "DEBUG.*=.*true" "$PROJECT_DIR/docker-compose.yml" 2>/dev/null; then
    log_high "DEBUG pode estar habilitado em produção"
else
    log_pass "DEBUG não está habilitado explicitamente"
fi

# Verificar HTTPS
if grep -q "listen 443\|ssl_certificate" "$PROJECT_DIR/docker/nginx/nginx.conf" 2>/dev/null && ! grep -q "#.*listen 443\|#.*ssl_certificate" "$PROJECT_DIR/docker/nginx/nginx.conf" 2>/dev/null; then
    log_medium "HTTPS configurado (verificar certificados)"
else
    log_medium "HTTPS não configurado (recomendado para produção)"
fi

# Verificar rate limiting
if grep -q "rate_limit\|limit_req" "$PROJECT_DIR/docker/nginx/nginx.conf" 2>/dev/null; then
    log_pass "Rate limiting configurado no Nginx"
else
    log_medium "Rate limiting não configurado (recomendado)"
fi

# Verificar security headers
if grep -q "X-Frame-Options\|X-Content-Type-Options\|Strict-Transport-Security" "$PROJECT_DIR/docker/nginx/nginx.conf" 2>/dev/null; then
    log_pass "Security headers configurados"
else
    log_medium "Security headers não configurados (recomendado)"
fi

# ============================================
# RESUMO FINAL
# ============================================
log_section "RESUMO DA AUDITORIA"

TOTAL=$((CRITICAL + HIGH + MEDIUM + LOW + PASSED))

echo -e "${RED}CRÍTICOS: $CRITICAL${NC}"
echo -e "${MAGENTA}ALTOS: $HIGH${NC}"
echo -e "${YELLOW}MÉDIOS: $MEDIUM${NC}"
echo -e "${BLUE}BAIXOS: $LOW${NC}"
echo -e "${GREEN}PASSARAM: $PASSED${NC}"
echo ""

if [ $CRITICAL -gt 0 ]; then
    echo -e "${RED}[ERROR] AUDITORIA FALHOU: $CRITICAL problema(s) CRÍTICO(S) encontrado(s)${NC}"
    echo -e "${RED}Corrija os problemas críticos antes de prosseguir para produção${NC}"
    exit 1
elif [ $HIGH -gt 0 ]; then
    echo -e "${YELLOW}[WARNING] AUDITORIA COM AVISOS: $HIGH problema(s) de ALTA prioridade${NC}"
    echo -e "${YELLOW}Recomendado corrigir antes de produção${NC}"
    exit 0
else
    echo -e "${GREEN}[OK] AUDITORIA PASSOU${NC}"
    echo -e "${GREEN}Nenhum problema crítico ou de alta prioridade encontrado${NC}"
    exit 0
fi

