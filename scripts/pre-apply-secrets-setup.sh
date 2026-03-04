#!/bin/bash
# ============================================================================
# pre-apply-secrets-setup.sh
# 
# Propósito: Adicionar secrets críticas ao Azure Key Vault ANTES do terraform apply
#
# Uso: ./scripts/pre-apply-secrets-setup.sh <key_vault_name>
# 
# Secrets a adicionar:
#   - grafana-admin-password (obrigatório para acesso a dashboards)
#   - slack-webhook-url (obrigatório para alertas)
#   - jwt-secret-key (para autenticação backend)
#   - encryption-key (para dados sensíveis)
#   - openai-api-key (para AI engine)
#   - database-url (PostgreSQL)
#   - redis-url (cache/celery broker)
#   - celery-broker-url (async tasks)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# FUNÇÕES
# ============================================================================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
    exit 1
}

# ============================================================================
# VALIDAÇÕES
# ============================================================================

if [ $# -lt 1 ]; then
    log_error "Uso: $0 <key_vault_name>"
    echo ""
    echo "Exemplo:"
    echo "  $0 akv-sky-prod-574052c0"
    exit 1
fi

KEY_VAULT_NAME="$1"

# Validar Azure CLI
if ! command -v az &> /dev/null; then
    log_error "Azure CLI não encontrado. Instale com: brew install azure-cli"
fi

# Validar que está logado no Azure
if ! az account show &> /dev/null; then
    log_error "Não está logado no Azure. Execute: az login"
fi

# Validar que Key Vault existe
if ! az keyvault show --name "$KEY_VAULT_NAME" &> /dev/null; then
    log_error "Key Vault '$KEY_VAULT_NAME' não encontrado ou sem acesso"
fi

log_info "Key Vault: $KEY_VAULT_NAME"

# ============================================================================
# CARREGAR SECRETS DO .env
# ============================================================================

if [ ! -f "$ENV_FILE" ]; then
    log_warn ".env não encontrado em $ENV_FILE"
    log_warn "Será necessário digitar secrets manualmente"
fi

# Função auxiliar para ler secret do .env ou prompt
get_secret() {
    local key="$1"
    local env_key="${2:-$key}"
    
    if [ -f "$ENV_FILE" ]; then
        local value=$(grep "^${env_key}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
        if [ -n "$value" ]; then
            echo "$value"
            return 0
        fi
    fi
    
    # Se não encontrou em .env, pedir input
    read -sp "Digite o valor para $key: " value
    echo ""
    if [ -z "$value" ]; then
        log_error "$key não pode ser vazio"
    fi
    echo "$value"
}

# ============================================================================
# CRIAR/ATUALIZAR SECRETS NO KEY VAULT
# ============================================================================

log_info "Adicionando secrets críticas ao Key Vault..."

# 1. Grafana Admin Password
log_info "Processando: grafana-admin-password"
GRAFANA_PASSWORD=$(get_secret "grafana-admin-password" "GRAFANA_ADMIN_PASSWORD")
az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name "grafana-admin-password" \
    --value "$GRAFANA_PASSWORD" \
    --output none
log_info "✓ grafana-admin-password adicionado"

# 2. Slack Webhook (ou usar placeholder)
log_info "Processando: slack-webhook-url"
read -p "Digite o Slack webhook URL (ou pressione Enter para placeholder): " SLACK_WEBHOOK
SLACK_WEBHOOK="${SLACK_WEBHOOK:-https://hooks.slack.com/services/YOUR/WEBHOOK/URL}"
az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name "slack-webhook-url" \
    --value "$SLACK_WEBHOOK" \
    --output none
log_info "✓ slack-webhook-url adicionado"

# 3. JWT Secret Key
log_info "Processando: jwt-secret-key"
JWT_SECRET=$(get_secret "jwt-secret-key" "JWT_SECRET_KEY")
az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name "jwt-secret-key" \
    --value "$JWT_SECRET" \
    --output none
log_info "✓ jwt-secret-key adicionado"

# 4. Encryption Key
log_info "Processando: encryption-key"
ENCRYPTION_KEY=$(get_secret "encryption-key" "ENCRYPTION_KEY")
az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name "encryption-key" \
    --value "$ENCRYPTION_KEY" \
    --output none
log_info "✓ encryption-key adicionado"

# 5. OpenAI API Key
log_info "Processando: openai-api-key"
OPENAI_KEY=$(get_secret "openai-api-key" "OPENAI_API_KEY")
az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name "openai-api-key" \
    --value "$OPENAI_KEY" \
    --output none
log_info "✓ openai-api-key adicionado"

# 6. Database URL
log_info "Processando: database-url"
DB_URL=$(get_secret "database-url" "DATABASE_URL")
az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name "database-url" \
    --value "$DB_URL" \
    --output none
log_info "✓ database-url adicionado"

# 7. Redis URL
log_info "Processando: redis-url"
REDIS_URL=$(get_secret "redis-url" "REDIS_URL")
az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name "redis-url" \
    --value "$REDIS_URL" \
    --output none
log_info "✓ redis-url adicionado"

# 8. Celery Broker URL
log_info "Processando: celery-broker-url"
CELERY_URL=$(get_secret "celery-broker-url" "CELERY_BROKER_URL")
az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name "celery-broker-url" \
    --value "$CELERY_URL" \
    --output none
log_info "✓ celery-broker-url adicionado"

# ============================================================================
# LISTAR SECRETS ADICIONADAS
# ============================================================================

log_info "Secrets adicionadas ao Key Vault:"
az keyvault secret list \
    --vault-name "$KEY_VAULT_NAME" \
    --output table \
    --query '[].name'

# ============================================================================
# INSTRUÇÕES FINAIS
# ============================================================================

echo ""
log_info "✓ Todas as secrets críticas foram adicionadas!"
echo ""
echo -e "${YELLOW}PRÓXIMOS PASSOS:${NC}"
echo "1. Verificar que ClusterSecretStore aponta para o Key Vault correto:"
echo "   kubectl edit clustersecretstore azure-keyvault"
echo ""
echo "2. Executar terraform apply:"
echo "   cd infra/aks"
echo "   terraform apply -var-file=terraform.tfvars.prod"
echo ""
echo "3. Após AKS criado, aplicar ArgoCD applications:"
echo "   kubectl apply -f gitops/bootstrap/prod/"
echo ""
echo "4. Validar que secrets foram sincronizadas:"
echo "   kubectl get secrets -n monitoring"
echo "   kubectl get secrets -n prod"
echo ""
echo "5. Verificar que Grafana pod iniciou com sucesso:"
echo "   kubectl logs -n monitoring -l app=grafana-prod"
echo ""
