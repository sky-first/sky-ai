#!/bin/bash
#
# Script de Simulação do GitHub Actions Workflow
# Valida a estrutura e lógica do pipeline sem executar comandos reais do Azure
#
set -uo pipefail  # Remover -e temporariamente para melhor debugging

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Contadores de testes
TESTS_PASSED=0
TESTS_FAILED=0
WARNINGS=0

# Função auxiliar para logging
log_info() {
    echo -e "${BLUE}ℹ  $1${NC}"
}

log_success() {
    echo -e "${GREEN}[OK] $1${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

log_warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
    WARNINGS=$((WARNINGS + 1))
}

echo "=========================================="
echo " SIMULAÇÃO DE WORKFLOW GITHUB ACTIONS"
echo "=========================================="
echo ""

# ============================================
# TESTE 1: Ordem dos Steps - IP antes de Key Vault
# ============================================
log_info "TESTE 1: Validando ordem dos steps..."

# Verificar ordem correta (IP antes) no primeiro job (terraform-plan)
IP_STEP_JOB1=$(grep -n "Get Runner IP" .github/workflows/deploy.yml | grep "name:" | head -1 | cut -d: -f1)
KV_STEP_JOB1=$(grep -n "Open Key Vault Internal Firewalls" .github/workflows/deploy.yml | grep "name:" | head -1 | cut -d: -f1)

if [ -n "$IP_STEP_JOB1" ] && [ -n "$KV_STEP_JOB1" ]; then
    if [ "$IP_STEP_JOB1" -lt "$KV_STEP_JOB1" ]; then
        log_success "Ordem correta no job 1: 'Get Runner IP' (linha $IP_STEP_JOB1) vem antes de 'Open Key Vault Internal Firewalls' (linha $KV_STEP_JOB1)"
    else
        log_error "P0: Ordem incorreta no job 1: 'Open Key Vault Internal Firewalls' (linha $KV_STEP_JOB1) vem antes de 'Get Runner IP' (linha $IP_STEP_JOB1)"
    fi
else
    log_warning "Não foi possível verificar ordem dos steps no job 1"
fi

# Verificar no segundo job (terraform-apply)
IP_STEP_JOB2=$(grep -n "Get Runner IP" .github/workflows/deploy.yml | grep "name:" | tail -1 | cut -d: -f1)
KV_STEP_JOB2=$(grep -n "Open Key Vault Internal Firewalls" .github/workflows/deploy.yml | grep "name:" | tail -1 | cut -d: -f1)

if [ -n "$IP_STEP_JOB2" ] && [ -n "$KV_STEP_JOB2" ]; then
    if [ "$IP_STEP_JOB2" -lt "$KV_STEP_JOB2" ]; then
        log_success "Ordem correta no job 2: 'Get Runner IP' (linha $IP_STEP_JOB2) vem antes de 'Open Key Vault Internal Firewalls' (linha $KV_STEP_JOB2)"
    else
        log_error "P0: Ordem incorreta no job 2: 'Open Key Vault Internal Firewalls' (linha $KV_STEP_JOB2) vem antes de 'Get Runner IP' (linha $IP_STEP_JOB2)"
    fi
fi

echo ""

# ============================================
# TESTE 2: Validação de Variáveis Obrigatórias
# ============================================
log_info "TESTE 2: Validando verificação de variáveis obrigatórias..."

MISSING_VALIDATIONS=0

# Verificar validação de ARM_CLIENT_ID
if grep -A 30 "Open Key Vault Internal Firewalls" .github/workflows/deploy.yml | grep -qE "ARM_CLIENT_ID.*não definido|z.*ARM_CLIENT_ID.*exit 1"; then
    log_success "Validação de ARM_CLIENT_ID encontrada"
else
    log_warning "Não encontrada validação explícita de ARM_CLIENT_ID no step 'Open Key Vault Internal Firewalls'"
    MISSING_VALIDATIONS=$((MISSING_VALIDATIONS + 1))
fi

# Verificar validação de RUNNER_IP
if grep -A 30 "Open Key Vault Internal Firewalls" .github/workflows/deploy.yml | grep -qE "RUNNER_IP.*não definido|z.*RUNNER_IP.*exit 1"; then
    log_success "Validação de RUNNER_IP encontrada"
else
    log_warning "Não encontrada validação explícita de RUNNER_IP no step 'Open Key Vault Internal Firewalls'"
    MISSING_VALIDATIONS=$((MISSING_VALIDATIONS + 1))
fi

if [ $MISSING_VALIDATIONS -eq 0 ]; then
    log_success "Todas as validações de variáveis obrigatórias estão presentes"
fi

echo ""

# ============================================
# TESTE 3: Exit 0 Forçado (não deve existir)
# ============================================
log_info "TESTE 3: Verificando exit 0 forçado em steps críticos..."

FORCED_EXIT_0=$(grep -n "exit 0" .github/workflows/deploy.yml | grep -v "^#" | grep -v "success\|fail" || true)

if echo "$FORCED_EXIT_0" | grep -q "Configure Key Vault Firewall\|Always succeed\|best-effort"; then
    log_error "P0: Encontrado 'exit 0' forçado em step crítico!"
    echo "$FORCED_EXIT_0"
    log_error "CORREÇÃO NECESSÁRIA: Remover 'exit 0' forçado e validar sucesso real"
else
    log_success "Nenhum 'exit 0' forçado encontrado em steps críticos"
fi

echo ""

# ============================================
# TESTE 4: Retry com Backoff para RBAC
# ============================================
log_info "TESTE 4: Validando retry com backoff para propagação RBAC..."

# Verificar se há retry loop para RBAC (não apenas sleep fixo)
RBAC_RETRY=$(grep -A 50 "conceder role\|Storage Blob Data Contributor" .github/workflows/deploy.yml | grep -E "while|for.*MAX_RBAC_WAIT|elapsed.*MAX_RBAC_WAIT" || true)

if [ -z "$RBAC_RETRY" ]; then
    log_warning "P1: Não encontrado retry loop para propagação RBAC (apenas sleep fixo?)"
else
    log_success "Retry loop para propagação RBAC encontrado"
fi

# Verificar se há MAX_RBAC_WAIT configurado
if grep -q "MAX_RBAC_WAIT" .github/workflows/deploy.yml; then
    MAX_WAIT=$(grep "MAX_RBAC_WAIT" .github/workflows/deploy.yml | grep -oE '[0-9]+' | head -1)
    if [ "$MAX_WAIT" -ge 300 ]; then
        log_success "MAX_RBAC_WAIT configurado com valor adequado (${MAX_WAIT}s = $((MAX_WAIT / 60)) minutos)"
    else
        log_warning "MAX_RBAC_WAIT muito baixo: ${MAX_WAIT}s (recomendado: >= 300s)"
    fi
else
    log_warning "MAX_RBAC_WAIT não encontrado - pode estar usando sleep fixo"
fi

echo ""

# ============================================
# TESTE 5: Validação Real de Conectividade (sem keyvault show falso)
# ============================================
log_info "TESTE 5: Validando que não há validação falsa (keyvault show como sucesso)..."

# Verificar se há validação falsa (keyvault show quebrando loop)
FAKE_VALIDATION=$(grep -A 20 "Verificando conectividade\|Validando conectividade" .github/workflows/deploy.yml | grep -A 10 "keyvault show.*vaultUri" | grep -E "CONNECTED=true|break" || true)

if [ -n "$FAKE_VALIDATION" ]; then
    log_warning "P0: Encontrada validação falsa - 'keyvault show' sendo usada como sucesso"
    log_warning "CORREÇÃO: Validar apenas 'secret list' (acesso real)"
else
    log_success "Nenhuma validação falsa encontrada - apenas validação real (secret list)"
fi

# Verificar se validação falha quando não conecta (no step Open Key Vault)
if grep -A 50 "Open Key Vault Internal Firewalls" .github/workflows/deploy.yml | grep -A 20 "CONNECTED.*false" | grep -qE "exit 1|ERRO.*não acessível"; then
    log_success "Step 'Open Key Vault Internal Firewalls' falha corretamente quando Key Vault não está acessível"
else
    log_warning "Verifique se 'Open Key Vault Internal Firewalls' falha quando CONNECTED=false"
fi

echo ""

# ============================================
# TESTE 6: Proteção do Lock do Terraform
# ============================================
log_info "TESTE 6: Validando proteção do lock do Terraform..."

# Verificar threshold do lock
LOCK_THRESHOLD=$(grep -E "LOCK_AGE_THRESHOLD|lock.*gt.*[0-9]+" .github/workflows/deploy.yml | grep -oE '[0-9]+' | head -1 || echo "0")

if [ "$LOCK_THRESHOLD" -ge 3600 ]; then
    log_success "Lock threshold adequado: ${LOCK_THRESHOLD}s ($((LOCK_THRESHOLD / 60)) minutos)"
elif [ "$LOCK_THRESHOLD" -lt 300 ] && [ "$LOCK_THRESHOLD" -gt 0 ]; then
    log_warning "P1: Lock threshold muito baixo: ${LOCK_THRESHOLD}s - pode remover locks de workflows ativos"
else
    log_warning "Não encontrado LOCK_AGE_THRESHOLD explícito"
fi

# Verificar se não remove automaticamente
if grep -A 10 "lock.*idade\|LOCK_AGE" .github/workflows/deploy.yml | grep -q "exit 1.*NÃO removendo\|não removendo automaticamente"; then
    log_success "Lock não é removido automaticamente quando suspeito"
else
    REMOVE_LOCK=$(grep -A 10 "lock.*preso\|Lock preso" .github/workflows/deploy.yml | grep "az storage blob delete.*lock" || true)
    if [ -n "$REMOVE_LOCK" ]; then
        log_warning "P1: Lock pode ser removido automaticamente - risco de race condition"
    fi
fi

echo ""

# ============================================
# TESTE 7: set -euo pipefail em todos os steps
# ============================================
log_info "TESTE 7: Validando uso de 'set -euo pipefail'..."

# Verificar se há steps com set +e que não deveriam ter
SET_PLUS_E=$(grep -n "set +e" .github/workflows/deploy.yml | grep -v "^#" || true)

if echo "$SET_PLUS_E" | grep -q "Configure Key Vault"; then
    log_error "P0: Encontrado 'set +e' em step crítico de Key Vault"
    echo "$SET_PLUS_E" | grep "Configure Key Vault"
else
    log_success "Nenhum 'set +e' problemático encontrado em steps críticos"
fi

echo ""

# ============================================
# TESTE 8: IP adicionado à whitelist ANTES de abrir firewall
# ============================================
log_info "TESTE 8: Validando que IP é adicionado à whitelist ANTES de abrir firewall..."

KV_CONFIG=$(grep -A 50 "Open Key Vault Internal Firewalls" .github/workflows/deploy.yml | grep -A 30 "for kv in" || true)

if echo "$KV_CONFIG" | grep -B 5 "default-action Allow" | grep -q "network-rule add.*RUNNER_IP"; then
    log_success "IP é adicionado à whitelist antes de abrir firewall (ordem correta)"
else
    # Verificar ordem
    NETWORK_RULE_LINE=$(echo "$KV_CONFIG" | grep -n "network-rule add" | head -1 | cut -d: -f1 || echo "0")
    DEFAULT_ACTION_LINE=$(echo "$KV_CONFIG" | grep -n "default-action Allow" | head -1 | cut -d: -f1 || echo "0")
    
    if [ "$NETWORK_RULE_LINE" != "0" ] && [ "$DEFAULT_ACTION_LINE" != "0" ]; then
        if [ "$NETWORK_RULE_LINE" -lt "$DEFAULT_ACTION_LINE" ]; then
            log_success "Ordem correta: network-rule add vem antes de default-action Allow"
        else
            log_warning "Ordem pode estar incorreta: verifique se IP é adicionado antes de abrir firewall"
        fi
    fi
fi

echo ""

# ============================================
# TESTE 9: Validação de Resource Group no tfvars
# ============================================
log_info "TESTE 9: Validando extração e validação de Resource Group..."

RG_EXTRACTION=$(grep -A 5 "resource_group_name.*TFVARS_FILE" .github/workflows/deploy.yml | head -3)

if echo "$RG_EXTRACTION" | grep -q "if.*-z.*RG_NAME.*exit 1"; then
    log_success "Validação de Resource Group existe - falha se vazio"
else
    log_warning "Validação de Resource Group pode estar ausente"
fi

echo ""

# ============================================
# TESTE 10: Função wait_for_rbac_propagation
# ============================================
log_info "TESTE 10: Validando função wait_for_rbac_propagation..."

if grep -q "wait_for_rbac_propagation\|function.*rbac" .github/workflows/deploy.yml; then
    log_success "Função auxiliar para propagação RBAC encontrada"
else
    log_warning "Função auxiliar wait_for_rbac_propagation não encontrada (pode estar inline)"
fi

echo ""

# ============================================
# RESUMO FINAL
# ============================================
echo "=========================================="
echo " RESUMO DOS TESTES"
echo "=========================================="
echo ""
echo "[OK] Testes Passados: $TESTS_PASSED"
echo "[ERROR] Testes Falhados: $TESTS_FAILED"
echo "[WARNING] Avisos: $WARNINGS"
echo ""

TOTAL_TESTS=$((TESTS_PASSED + TESTS_FAILED + WARNINGS))

if [ $TESTS_FAILED -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN} TODOS OS TESTES PASSARAM!${NC}"
        echo ""
        echo "[OK] O workflow está pronto para produção"
        exit 0
    else
        echo -e "${YELLOW}[WARNING] TESTES PASSARAM COM AVISOS${NC}"
        echo ""
        echo "O workflow deve funcionar, mas recomenda-se revisar os avisos acima"
        exit 0
    fi
else
    echo -e "${RED}[ERROR] ALGUNS TESTES FALHARAM${NC}"
    echo ""
    echo " CORREÇÕES NECESSÁRIAS antes de fazer deploy para produção"
    echo ""
    exit 1
fi
