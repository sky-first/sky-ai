#!/bin/bash
#
# Análise Minuciosa de Deploy Parcial e Problemas de Re-deploy
# Foca em problemas que impedem conclusão após deploy parcial bem-sucedido
#
set -uo pipefail

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Contadores
ISSUES_FOUND=0
CRITICAL_ISSUES=0
WARNINGS=0

log_critical() {
    echo -e "${RED}🔴 CRÍTICO: $1${NC}"
    CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1))
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
}

log_warning() {
    echo -e "${YELLOW}⚠️  AVISO: $1${NC}"
    WARNINGS=$((WARNINGS + 1))
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

echo "=========================================="
echo "🔍 ANÁLISE MINUCIOSA - DEPLOY PARCIAL"
echo "=========================================="
echo "Focando em problemas que impedem re-deploy após deploy parcial"
echo ""

# ============================================
# ANÁLISE 1: Cleanup de Key Vault Firewall
# ============================================
echo -e "${CYAN}📋 ANÁLISE 1: Cleanup de Key Vault Firewall${NC}"
echo ""

RESTRICT_STEP=$(grep -A 10 "Restrict Key Vault Internal Firewalls" .github/workflows/deploy.yml | head -15)

if [ -z "$RESTRICT_STEP" ]; then
    log_critical "Step 'Restrict Key Vault Internal Firewalls' não encontrado"
    log_critical "Key Vaults ficarão com firewall ABERTO após deploy (risco de segurança)"
else
    # Verificar se usa always() e se restaura corretamente
    if echo "$RESTRICT_STEP" | grep -q "if: always()"; then
        log_success "Step de restrição usa 'if: always()' - executa mesmo em falha"
        
        # Verificar se restaura para Deny
        if echo "$RESTRICT_STEP" | grep -q "default-action Deny"; then
            log_success "Firewall é restaurado para 'Deny' após deploy"
        else
            log_critical "Firewall NÃO é restaurado para 'Deny' após deploy"
            log_critical "Key Vaults ficarão com firewall ABERTO permanentemente"
        fi
    else
        log_warning "Step de restrição não usa 'if: always()' - pode não executar em falha"
    fi
    
    # Verificar se lista de KV está disponível
    if echo "$RESTRICT_STEP" | grep -q "\${.*KV_OVERRIDE_LIST"; then
        log_success "Usa KV_OVERRIDE_LIST para cleanup (correto)"
    else
        log_warning "Pode não ter lista de Key Vaults para cleanup"
    fi
fi

echo ""

# ============================================
# ANÁLISE 2: State do Terraform Após Deploy Parcial
# ============================================
echo -e "${CYAN}📋 ANÁLISE 2: State do Terraform Após Deploy Parcial${NC}"
echo ""

# Verificar se há validação de state antes de plan/apply
STATE_CHECK=$(grep -A 5 "terraform state\|state show\|state list" .github/workflows/deploy.yml | head -20)

if echo "$STATE_CHECK" | grep -q "state show.*azurerm_resource_group"; then
    log_success "Verifica se Resource Group está no state do Terraform"
else
    log_warning "Não encontrada validação explícita de state antes de plan/apply"
fi

# Verificar tratamento de drift
if grep -q "refresh-only\|terraform refresh" .github/workflows/deploy.yml; then
    log_success "Há comando para sincronizar state (refresh)"
else
    log_warning "Não encontrado tratamento explícito de drift do state"
fi

echo ""

# ============================================
# ANÁLISE 3: Recursos Criados Parcialmente
# ============================================
echo -e "${CYAN}📋 ANÁLISE 3: Recursos Criados Parcialmente${NC}"
echo ""

# Verificar se há import automático de recursos existentes
IMPORT_STEP=$(grep -A 3 "terraform import\|import-resources" .github/workflows/deploy.yml | head -5)

if [ -n "$IMPORT_STEP" ]; then
    log_success "Há step para importar recursos existentes"
else
    log_warning "Não encontrado step para importar recursos existentes"
    log_warning "Recursos criados parcialmente podem causar conflito"
fi

echo ""

# ============================================
# ANÁLISE 4: Dependências Entre Recursos
# ============================================
echo -e "${CYAN}📋 ANÁLISE 4: Dependências Entre Recursos${NC}"
echo ""

# Verificar se há depends_on no Terraform
DEPENDS_ON=$(grep -r "depends_on" infra/aks/*.tf 2>/dev/null | head -5 || true)

if [ -n "$DEPENDS_ON" ]; then
    log_success "Há depends_on configurado no Terraform (dependências explícitas)"
else
    log_warning "Não encontrado depends_on - dependências implícitas podem causar problemas"
fi

# Verificar se há lifecycle blocks
LIFECYCLE=$(grep -r "lifecycle" infra/aks/*.tf 2>/dev/null | head -3 || true)

if [ -n "$LIFECYCLE" ]; then
    log_success "Há lifecycle blocks configurados"
    # Verificar ignore_changes
    if grep -r "ignore_changes" infra/aks/*.tf 2>/dev/null | grep -q "ip_rules\|network_acls"; then
        log_success "ignore_changes configurado para ip_rules/network_acls (evita conflito)"
    fi
else
    log_warning "Lifecycle blocks não encontrados"
fi

echo ""

# ============================================
# ANÁLISE 5: Validações que Podem Falhar em Re-deploy
# ============================================
echo -e "${CYAN}📋 ANÁLISE 5: Validações que Podem Falhar em Re-deploy${NC}"
echo ""

# Verificar validação de Storage Account/Container
STORAGE_VALIDATION=$(grep -A 20 "Validate Terraform Backend" .github/workflows/deploy.yml | grep "storage container" | head -5)

if echo "$STORAGE_VALIDATION" | grep -q "container show\|container create"; then
    # Verificar se lida com container já existente
    if echo "$STORAGE_VALIDATION" | grep -q "CONTAINER_EXISTS\|já existe\|already exists"; then
        log_success "Validação lida com container já existente (idempotente)"
    else
        log_warning "Validação pode tentar criar container já existente (pode falhar)"
    fi
else
    log_warning "Validação de container pode não ser idempotente"
fi

# Verificar validação de Key Vault
KV_VALIDATION=$(grep -A 30 "Open Key Vault Internal Firewalls" .github/workflows/deploy.yml | grep -E "keyvault (show|update|network-rule)" | head -5)

if echo "$KV_VALIDATION" | grep -q "network-rule add.*only-show-errors\|already whitelisted"; then
    log_success "Configuração de Key Vault é idempotente"
else
    log_warning "Configuração de Key Vault pode falhar em re-deploy (IP já na whitelist)"
fi

echo ""

# ============================================
# ANÁLISE 6: Timeout e Retry
# ============================================
echo -e "${CYAN}📋 ANÁLISE 6: Timeout e Retry${NC}"
echo ""

# Verificar timeouts dos jobs
TIMEOUTS=$(grep "timeout-minutes:" .github/workflows/deploy.yml)

if echo "$TIMEOUTS" | grep -q "terraform-plan.*30\|terraform-apply.*60"; then
    log_success "Timeouts configurados adequadamente"
else
    log_warning "Verifique se timeouts são suficientes para deploy completo"
fi

# Verificar retry em operações críticas
RBAC_RETRY=$(grep -c "MAX_RBAC_WAIT\|wait_for_rbac_propagation" .github/workflows/deploy.yml || echo "0")

if [ "$RBAC_RETRY" -ge "2" ]; then
    log_success "Retry para propagação RBAC está presente em múltiplos lugares"
else
    log_warning "Retry para propagação RBAC pode estar ausente em alguns lugares"
fi

echo ""

# ============================================
# ANÁLISE 7: Rollback e Recuperação
# ============================================
echo -e "${CYAN}📋 ANÁLISE 7: Rollback e Recuperação${NC}"
echo ""

ROLLBACK_JOB=$(grep -A 5 "rollback\|Rollback on Failure" .github/workflows/deploy.yml | head -10)

if [ -n "$ROLLBACK_JOB" ]; then
    log_success "Há job de rollback configurado"
    
    # Verificar se rollback restaura firewall
    if echo "$ROLLBACK_JOB" | grep -q "Restrict Key Vault\|default-action Deny"; then
        log_success "Rollback restaura firewall do Key Vault"
    else
        log_warning "Rollback pode não restaurar firewall do Key Vault"
    fi
else
    log_warning "Não encontrado job específico de rollback"
fi

echo ""

# ============================================
# ANÁLISE 8: Artifacts e State Backup
# ============================================
echo -e "${CYAN}📋 ANÁLISE 8: Artifacts e State Backup${NC}"
echo ""

# Verificar backup de state
STATE_BACKUP=$(grep -A 10 "Save State Backup\|State Backup\|state pull" .github/workflows/deploy.yml | head -10)

if [ -n "$STATE_BACKUP" ]; then
    log_success "Há backup de state do Terraform"
else
    log_warning "Não encontrado backup de state antes de apply"
    log_warning "State corrompido não pode ser restaurado facilmente"
fi

# Verificar upload de artifacts
ARTIFACT_UPLOAD=$(grep -A 3 "upload-artifact\|Upload.*Artifact" .github/workflows/deploy.yml | head -5)

if [ -n "$ARTIFACT_UPLOAD" ]; then
    log_success "Há upload de artifacts (tfplan, state backup, etc)"
else
    log_warning "Artifacts podem não estar sendo salvos para recuperação"
fi

echo ""

# ============================================
# ANÁLISE 9: Variáveis de Ambiente e Secrets
# ============================================
echo -e "${CYAN}📋 ANÁLISE 9: Variáveis de Ambiente e Secrets${NC}"
echo ""

# Verificar se todas as variáveis necessárias estão definidas
REQUIRED_VARS=("ARM_SUBSCRIPTION_ID" "ARM_TENANT_ID" "ARM_CLIENT_ID" "TF_BACKEND_STORAGE_ACCOUNT" "TF_BACKEND_CONTAINER")

for var in "${REQUIRED_VARS[@]}"; do
    if grep -q "\${var}:\|${var}:" .github/workflows/deploy.yml; then
        log_success "Variável $var está sendo usada"
    else
        log_warning "Variável $var pode não estar definida ou usada"
    fi
done

echo ""

# ============================================
# ANÁLISE 10: Problemas Específicos de Re-deploy
# ============================================
echo -e "${CYAN}📋 ANÁLISE 10: Problemas Específicos de Re-deploy${NC}"
echo ""

# Verificar se há tratamento para recursos já existentes
EXISTING_RESOURCES=$(grep -r "terraform import\|already exists\|resource.*already" .github/workflows/deploy.yml infra/aks/*.tf 2>/dev/null | head -3 || true)

if [ -n "$EXISTING_RESOURCES" ]; then
    log_success "Há algum tratamento para recursos já existentes"
else
    log_warning "Pode não haver tratamento para recursos já criados em deploy anterior"
fi

# Verificar se workspace está sendo validado
WORKSPACE_CHECK=$(grep -A 5 "terraform workspace\|Validate.*Workspace" .github/workflows/deploy.yml | head -10)

if [ -n "$WORKSPACE_CHECK" ]; then
    log_success "Workspace do Terraform é validado"
else
    log_warning "Workspace pode não estar sendo validado - risco de aplicar no workspace errado"
fi

echo ""

# ============================================
# RESUMO FINAL
# ============================================
echo "=========================================="
echo "📊 RESUMO DA ANÁLISE"
echo "=========================================="
echo ""
echo "🔴 Problemas Críticos: $CRITICAL_ISSUES"
echo "⚠️  Avisos: $WARNINGS"
echo "✅ Total de Itens Analisados: $ISSUES_FOUND"
echo ""

if [ $CRITICAL_ISSUES -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}🎉 NENHUM PROBLEMA ENCONTRADO!${NC}"
        echo "O workflow está preparado para re-deploy após deploy parcial"
        exit 0
    else
        echo -e "${YELLOW}⚠️  WORKFLOW FUNCIONAL COM AVISOS${NC}"
        echo "Recomenda-se revisar os avisos acima para garantir robustez"
        exit 0
    fi
else
    echo -e "${RED}❌ PROBLEMAS CRÍTICOS ENCONTRADOS${NC}"
    echo "Correções obrigatórias antes de re-deploy"
    exit 1
fi
