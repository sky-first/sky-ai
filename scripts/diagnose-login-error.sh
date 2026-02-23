#!/bin/bash
# Script de Diagnóstico - Erro 500 no Login
# Diagnostica problemas relacionados ao erro 500 durante o login
# Uso: ./scripts/diagnose-login-error.sh [VM_IP] [SSH_USER]

set -eu

VM_IP="${1:-}"
SSH_USER="${2:-azureuser}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Função para imprimir seção
print_section() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}"
}

# Função para imprimir sucesso
print_success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

# Função para imprimir erro
print_error() {
    echo -e "${RED}[ERROR] $1${NC}"
    ((ERRORS++))
}

# Função para imprimir aviso
print_warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
    ((WARNINGS++))
}

# Função para imprimir info
print_info() {
    echo -e "${BLUE}ℹ  $1${NC}"
}

# Verificar se estamos na VM ou precisamos SSH
if [ -z "$VM_IP" ]; then
    # Assumir que estamos executando diretamente na VM
    REMOTE_CMD=""
    print_info "Executando diagnóstico localmente na VM..."
else
    # Executar via SSH
    SSH_KEY="$PROJECT_ROOT/keys/azure/team/id_rsa_staging"
    if [ ! -f "$SSH_KEY" ]; then
        SSH_KEY="$PROJECT_ROOT/keys/azure/team/id_rsa_poc"
    fi
    
    if [ ! -f "$SSH_KEY" ]; then
        print_error "Chave SSH não encontrada. Procurando em: $SSH_KEY"
        exit 1
    fi
    
    chmod 600 "$SSH_KEY"
    REMOTE_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10 $SSH_USER@$VM_IP"
    print_info "Conectando via SSH à VM: $VM_IP"
fi

print_section "DIAGNÓSTICO DE ERRO 500 NO LOGIN"

# ============================================
# 1. VERIFICAR STATUS DOS CONTAINERS
# ============================================
print_section "1. Status dos Containers"

if [ -z "$VM_IP" ]; then
    BACKEND_STATUS=$(docker ps --filter "name=backend" --format "{{.Status}}" 2>/dev/null || echo "NOT_RUNNING")
    POSTGRES_STATUS=$(docker ps --filter "name=postgres" --format "{{.Status}}" 2>/dev/null || echo "NOT_RUNNING")
else
    BACKEND_STATUS=$($REMOTE_CMD "docker ps --filter 'name=backend' --format '{{.Status}}' 2>/dev/null || echo 'NOT_RUNNING'" 2>&1)
    POSTGRES_STATUS=$($REMOTE_CMD "docker ps --filter 'name=postgres' --format '{{.Status}}' 2>/dev/null || echo 'NOT_RUNNING'" 2>&1)
fi

if [[ "$BACKEND_STATUS" == *"Up"* ]] || [[ "$BACKEND_STATUS" == *"running"* ]]; then
    print_success "Backend container está rodando: $BACKEND_STATUS"
else
    print_error "Backend container NÃO está rodando: $BACKEND_STATUS"
fi

if [[ "$POSTGRES_STATUS" == *"Up"* ]] || [[ "$POSTGRES_STATUS" == *"running"* ]]; then
    print_success "PostgreSQL container está rodando: $POSTGRES_STATUS"
else
    print_error "PostgreSQL container NÃO está rodando: $POSTGRES_STATUS"
fi

# ============================================
# 2. VERIFICAR LOGS DO BACKEND (ÚLTIMOS ERROS)
# ============================================
print_section "2. Logs do Backend (últimos 50 erros)"

if [ -z "$VM_IP" ]; then
    BACKEND_LOGS=$(docker logs ai_saas_backend_prod --tail 100 2>&1 | grep -i -E "(error|exception|traceback|500|login)" | tail -20 || echo "Nenhum log encontrado")
else
    BACKEND_LOGS=$($REMOTE_CMD "docker logs ai_saas_backend_prod --tail 100 2>&1 | grep -i -E '(error|exception|traceback|500|login)' | tail -20 || echo 'Nenhum log encontrado'" 2>&1)
fi

if [ -z "$BACKEND_LOGS" ] || [[ "$BACKEND_LOGS" == *"Nenhum log encontrado"* ]]; then
    print_warning "Nenhum erro recente encontrado nos logs"
else
    echo -e "${YELLOW}$BACKEND_LOGS${NC}"
    print_info "Verifique os erros acima para identificar o problema"
fi

# ============================================
# 3. VERIFICAR CONFIGURAÇÃO DEBUG
# ============================================
print_section "3. Configuração DEBUG"

if [ -z "$VM_IP" ]; then
    DEBUG_VALUE=$(docker exec ai_saas_backend_prod env 2>/dev/null | grep "^DEBUG=" || echo "DEBUG não encontrado")
else
    DEBUG_VALUE=$($REMOTE_CMD "docker exec ai_saas_backend_prod env 2>/dev/null | grep '^DEBUG=' || echo 'DEBUG não encontrado'" 2>&1)
fi

if [[ "$DEBUG_VALUE" == *"DEBUG=true"* ]] || [[ "$DEBUG_VALUE" == *"DEBUG=True"* ]]; then
    print_success "DEBUG está habilitado - erros mostrarão detalhes completos"
elif [[ "$DEBUG_VALUE" == *"DEBUG=false"* ]] || [[ "$DEBUG_VALUE" == *"DEBUG=False"* ]]; then
    print_warning "DEBUG está desabilitado - erros mostrarão apenas 'An unexpected error occurred'"
    print_info "Considere habilitar DEBUG temporariamente para diagnóstico: DEBUG=true"
else
    print_warning "Não foi possível determinar configuração DEBUG: $DEBUG_VALUE"
fi

# ============================================
# 4. TESTAR CONEXÃO COM BANCO DE DADOS
# ============================================
print_section "4. Teste de Conexão com Banco de Dados"

if [ -z "$VM_IP" ]; then
    DB_TEST=$(docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -c "SELECT version();" 2>&1 || echo "ERRO")
else
    DB_TEST=$($REMOTE_CMD "docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -c 'SELECT version();' 2>&1 || echo 'ERRO'" 2>&1)
fi

if [[ "$DB_TEST" == *"PostgreSQL"* ]]; then
    print_success "Conexão com banco de dados OK"
    echo "$DB_TEST" | head -1
else
    print_error "Falha na conexão com banco de dados"
    echo "$DB_TEST"
fi

# ============================================
# 5. VERIFICAR SE TABELAS EXISTEM
# ============================================
print_section "5. Verificação de Tabelas"

TABLES_TO_CHECK=("users" "planets" "spaces" "planet_members")

for table in "${TABLES_TO_CHECK[@]}"; do
    if [ -z "$VM_IP" ]; then
        TABLE_EXISTS=$(docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '$table');" 2>&1 | tr -d ' ' || echo "false")
    else
        TABLE_EXISTS=$($REMOTE_CMD "docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c \"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '$table');\" 2>&1 | tr -d ' ' || echo 'false'" 2>&1)
    fi
    
    if [[ "$TABLE_EXISTS" == *"t"* ]] || [[ "$TABLE_EXISTS" == *"true"* ]]; then
        print_success "Tabela '$table' existe"
    else
        print_error "Tabela '$table' NÃO existe"
    fi
done

# ============================================
# 6. VERIFICAR CONSTRAINTS E FOREIGN KEYS
# ============================================
print_section "6. Verificação de Constraints"

if [ -z "$VM_IP" ]; then
    FK_PLANETS=$(docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c "SELECT COUNT(*) FROM information_schema.table_constraints WHERE constraint_type = 'FOREIGN KEY' AND table_name = 'planets';" 2>&1 | tr -d ' ' || echo "0")
    FK_SPACES=$(docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c "SELECT COUNT(*) FROM information_schema.table_constraints WHERE constraint_type = 'FOREIGN KEY' AND table_name = 'spaces';" 2>&1 | tr -d ' ' || echo "0")
else
    FK_PLANETS=$($REMOTE_CMD "docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c \"SELECT COUNT(*) FROM information_schema.table_constraints WHERE constraint_type = 'FOREIGN KEY' AND table_name = 'planets';\" 2>&1 | tr -d ' ' || echo '0'" 2>&1)
    FK_SPACES=$($REMOTE_CMD "docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c \"SELECT COUNT(*) FROM information_schema.table_constraints WHERE constraint_type = 'FOREIGN KEY' AND table_name = 'spaces';\" 2>&1 | tr -d ' ' || echo '0'" 2>&1)
fi

if [ "$FK_PLANETS" -gt 0 ] 2>/dev/null; then
    print_success "Tabela 'planets' tem $FK_PLANETS foreign key(s)"
else
    print_warning "Tabela 'planets' não tem foreign keys configuradas ou erro ao verificar"
fi

if [ "$FK_SPACES" -gt 0 ] 2>/dev/null; then
    print_success "Tabela 'spaces' tem $FK_SPACES foreign key(s)"
else
    print_warning "Tabela 'spaces' não tem foreign keys configuradas ou erro ao verificar"
fi

# ============================================
# 7. VERIFICAR USUÁRIOS NO BANCO
# ============================================
print_section "7. Verificação de Usuários"

if [ -z "$VM_IP" ]; then
    USER_COUNT=$(docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c "SELECT COUNT(*) FROM users WHERE deleted_at IS NULL;" 2>&1 | tr -d ' ' || echo "0")
    TEST_USER=$(docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c "SELECT id, email, name FROM users WHERE email = 'test@example.com' LIMIT 1;" 2>&1 || echo "ERRO")
else
    USER_COUNT=$($REMOTE_CMD "docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c \"SELECT COUNT(*) FROM users WHERE deleted_at IS NULL;\" 2>&1 | tr -d ' ' || echo '0'" 2>&1)
    TEST_USER=$($REMOTE_CMD "docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c \"SELECT id, email, name FROM users WHERE email = 'test@example.com' LIMIT 1;\" 2>&1 || echo 'ERRO'" 2>&1)
fi

if [ "$USER_COUNT" -gt 0 ] 2>/dev/null; then
    print_success "Existem $USER_COUNT usuário(s) no banco"
else
    print_warning "Nenhum usuário encontrado no banco ou erro ao verificar"
fi

if [[ "$TEST_USER" == *"test@example.com"* ]]; then
    print_success "Usuário de teste encontrado:"
    echo "$TEST_USER" | grep -v "^$" | head -1
else
    print_warning "Usuário 'test@example.com' não encontrado"
fi

# ============================================
# 8. TESTAR CRIAÇÃO DE PLANET/SPACE (SIMULAÇÃO)
# ============================================
print_section "8. Teste de Criação de Planet/Space"

if [ -z "$VM_IP" ]; then
    # Pegar ID de um usuário existente
    USER_ID=$(docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c "SELECT id FROM users WHERE deleted_at IS NULL LIMIT 1;" 2>&1 | tr -d ' ' | head -1 || echo "")
    
    if [ -n "$USER_ID" ] && [ ${#USER_ID} -gt 10 ]; then
        print_info "Testando criação de planet para usuário: $USER_ID"
        
        # Verificar se já tem planet
        EXISTING_PLANET=$(docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c "SELECT COUNT(*) FROM planets WHERE owner_id = '$USER_ID' AND deleted_at IS NULL;" 2>&1 | tr -d ' ' || echo "0")
        
        if [ "$EXISTING_PLANET" -gt 0 ] 2>/dev/null; then
            print_success "Usuário já tem $EXISTING_PLANET planet(s)"
        else
            print_info "Usuário não tem planets - isso é esperado para novos usuários"
        fi
        
        # Verificar se já tem space
        EXISTING_SPACE=$(docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c "SELECT COUNT(*) FROM spaces WHERE created_by = '$USER_ID' AND deleted_at IS NULL;" 2>&1 | tr -d ' ' || echo "0")
        
        if [ "$EXISTING_SPACE" -gt 0 ] 2>/dev/null; then
            print_success "Usuário já tem $EXISTING_SPACE space(s)"
        else
            print_info "Usuário não tem spaces - isso é esperado para novos usuários"
        fi
    else
        print_warning "Não foi possível encontrar um usuário para teste"
    fi
else
    USER_ID=$($REMOTE_CMD "docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c \"SELECT id FROM users WHERE deleted_at IS NULL LIMIT 1;\" 2>&1 | tr -d ' ' | head -1 || echo ''" 2>&1)
    
    if [ -n "$USER_ID" ] && [ ${#USER_ID} -gt 10 ]; then
        print_info "Testando criação de planet para usuário: $USER_ID"
        
        EXISTING_PLANET=$($REMOTE_CMD "docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c \"SELECT COUNT(*) FROM planets WHERE owner_id = '$USER_ID' AND deleted_at IS NULL;\" 2>&1 | tr -d ' ' || echo '0'" 2>&1)
        EXISTING_SPACE=$($REMOTE_CMD "docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c \"SELECT COUNT(*) FROM spaces WHERE created_by = '$USER_ID' AND deleted_at IS NULL;\" 2>&1 | tr -d ' ' || echo '0'" 2>&1)
        
        if [ "$EXISTING_PLANET" -gt 0 ] 2>/dev/null; then
            print_success "Usuário já tem $EXISTING_PLANET planet(s)"
        else
            print_info "Usuário não tem planets"
        fi
        
        if [ "$EXISTING_SPACE" -gt 0 ] 2>/dev/null; then
            print_success "Usuário já tem $EXISTING_SPACE space(s)"
        else
            print_info "Usuário não tem spaces"
        fi
    else
        print_warning "Não foi possível encontrar um usuário para teste"
    fi
fi

# ============================================
# 9. VERIFICAR LOGS RECENTES DE LOGIN
# ============================================
print_section "9. Logs Recentes de Login (últimas 30 linhas)"

if [ -z "$VM_IP" ]; then
    LOGIN_LOGS=$(docker logs ai_saas_backend_prod --tail 50 2>&1 | grep -i -E "(login|auth|ensure_default)" | tail -10 || echo "Nenhum log de login encontrado")
else
    LOGIN_LOGS=$($REMOTE_CMD "docker logs ai_saas_backend_prod --tail 50 2>&1 | grep -i -E '(login|auth|ensure_default)' | tail -10 || echo 'Nenhum log de login encontrado'" 2>&1)
fi

if [ -z "$LOGIN_LOGS" ] || [[ "$LOGIN_LOGS" == *"Nenhum log"* ]]; then
    print_warning "Nenhum log de login recente encontrado"
else
    echo -e "${YELLOW}$LOGIN_LOGS${NC}"
fi

# ============================================
# 10. VERIFICAR ERROS DE BANCO DE DADOS
# ============================================
print_section "10. Verificação de Erros no Banco"

if [ -z "$VM_IP" ]; then
    DB_ERRORS=$(docker logs ai_saas_postgres_prod --tail 100 2>&1 | grep -i -E "(error|fatal|panic)" | tail -10 || echo "Nenhum erro encontrado")
else
    DB_ERRORS=$($REMOTE_CMD "docker logs ai_saas_postgres_prod --tail 100 2>&1 | grep -i -E '(error|fatal|panic)' | tail -10 || echo 'Nenhum erro encontrado'" 2>&1)
fi

if [ -z "$DB_ERRORS" ] || [[ "$DB_ERRORS" == *"Nenhum erro"* ]]; then
    print_success "Nenhum erro recente no banco de dados"
else
    print_error "Erros encontrados no banco de dados:"
    echo -e "${RED}$DB_ERRORS${NC}"
fi

# ============================================
# RESUMO FINAL
# ============================================
print_section "RESUMO DO DIAGNÓSTICO"

echo ""
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    print_success "Nenhum problema crítico encontrado!"
    echo ""
    print_info "Se o erro 500 persistir, verifique:"
    echo "  1. Logs completos do backend: docker logs ai_saas_backend_prod --tail 200"
    echo "  2. Habilitar DEBUG temporariamente: DEBUG=true no .env"
    echo "  3. Verificar se as migrations foram executadas: docker exec ai_saas_backend_prod alembic current"
elif [ $ERRORS -eq 0 ]; then
    print_warning "Encontrados $WARNINGS aviso(s), mas nenhum erro crítico"
    echo ""
    print_info "Recomendações:"
    echo "  1. Verifique os avisos acima"
    echo "  2. Considere habilitar DEBUG para mais detalhes"
else
    print_error "Encontrados $ERRORS erro(s) e $WARNINGS aviso(s)"
    echo ""
    print_info "Ações recomendadas:"
    echo "  1. Corrija os erros listados acima"
    echo "  2. Verifique logs completos: docker logs ai_saas_backend_prod --tail 200"
    echo "  3. Verifique se as migrations estão atualizadas"
    echo "  4. Considere reiniciar os containers se necessário"
fi

echo ""
print_info "Para ver logs em tempo real:"
if [ -z "$VM_IP" ]; then
    echo "  docker logs -f ai_saas_backend_prod"
else
    echo "  $REMOTE_CMD 'docker logs -f ai_saas_backend_prod'"
fi

echo ""
exit 0

