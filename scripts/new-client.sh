#!/usr/bin/env bash
# =============================================================================
# new-client.sh — Script de Onboarding de Novo Cliente VIP
# =============================================================================
#
# Uso:
#   ./scripts/new-client.sh \
#     --client   nome-do-cliente \    # ex: banco-c (sem espaços, lowercase)
#     --domain   cliente.com.br \     # domínio principal do cliente
#     --acr      skyacrbancocXXXX \   # nome do ACR (obtido após terraform apply)
#     --dr       true|false           # cliente contratou Geo-DR?
#
# Exemplos:
#   # Cliente sem DR:
#   ./scripts/new-client.sh --client banco-c --domain bancoc.com.br --acr skyacrbancoc1234 --dr false
#
#   # Cliente com DR:
#   ./scripts/new-client.sh --client banco-d --domain bancod.com.br --acr skyacrbancodfff9 --dr true
#
# O script cria automaticamente:
#   infra/aks/environments/{client}.tfvars
#   gitops/bootstrap/clients/{client}/primary/*.yaml
#   gitops/bootstrap/clients/{client}/dr/*.yaml     (se --dr true)
#   gitops/charts/common-app/values-{client}-*.yaml
#
# Após rodar o script:
#   1. Revise os arquivos gerados (IPs, domínios, CIDRs)
#   2. git add . && git commit -m "feat(clients): onboarding {client}"
#   3. terraform apply -var-file=infra/aks/environments/{client}.tfvars
#   4. Configure o ArgoCD do cluster do cliente apontando para:
#      gitops/bootstrap/clients/{client}/primary/
# =============================================================================

set -euo pipefail

# ─── Cores para output ────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ─── Parse argumentos ─────────────────────────────────────────────────────────
CLIENT=""
DOMAIN=""
ACR=""
DR="false"

while [[ $# -gt 0 ]]; do
  case $1 in
    --client)  CLIENT="$2";  shift 2 ;;
    --domain)  DOMAIN="$2";  shift 2 ;;
    --acr)     ACR="$2";     shift 2 ;;
    --dr)      DR="$2";      shift 2 ;;
    *) log_error "Argumento desconhecido: $1. Use --client, --domain, --acr, --dr" ;;
  esac
done

# ─── Validações ───────────────────────────────────────────────────────────────
[[ -z "$CLIENT" ]] && log_error "--client é obrigatório. Ex: --client banco-c"
[[ -z "$DOMAIN" ]] && log_error "--domain é obrigatório. Ex: --domain bancoc.com.br"
[[ -z "$ACR"    ]] && log_error "--acr é obrigatório. Ex: --acr skyacrbancoc1234 (obtido após terraform apply)"
[[ "$DR" != "true" && "$DR" != "false" ]] && log_error "--dr deve ser 'true' ou 'false'"

# Validar formato do client (lowercase, sem espaços)
if [[ ! "$CLIENT" =~ ^[a-z0-9-]+$ ]]; then
  log_error "--client deve conter apenas letras minúsculas, números e hífens. Ex: banco-c"
fi

# ─── Verificar raiz do repositório ────────────────────────────────────────────
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || log_error "Não está dentro de um repositório git."
cd "$REPO_ROOT"

# Verificar se cliente já existe
if [[ -d "gitops/bootstrap/clients/${CLIENT}" ]]; then
  log_error "Cliente '${CLIENT}' já existe em gitops/bootstrap/clients/${CLIENT}"
fi

# ─── Calcular CIDRs disponíveis ───────────────────────────────────────────────
# Encontrar o próximo octeto disponível baseado nos clients existentes
EXISTING_CLIENTS=$(ls infra/aks/environments/ 2>/dev/null | grep -v 'staging\|prod\|client-vip' | wc -l | tr -d ' ')
BASE_OCTET=$(( 30 + EXISTING_CLIENTS * 10 ))
DR_OCTET=$(( BASE_OCTET + 2 ))
SVC_OCTET=$(( BASE_OCTET + 4 ))

VNET_CIDR="10.${BASE_OCTET}.0.0/16"
DR_CIDR="10.${DR_OCTET}.0.0/16"
SVC_CIDR="10.${SVC_OCTET}.0.0/16"

# ─── Banner ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        Sky — Onboarding de Novo Cliente VIP         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
log_info "Cliente:    ${CLIENT}"
log_info "Domínio:    ${DOMAIN}"
log_info "ACR:        ${ACR}.azurecr.io"
log_info "Geo-DR:     ${DR}"
log_info "VNet CIDR:  ${VNET_CIDR}"
[[ "$DR" == "true" ]] && log_info "DR CIDR:    ${DR_CIDR}"
log_info "Svc CIDR:   ${SVC_CIDR}"
echo ""

# ─── 1. Criar Terraform tfvars ────────────────────────────────────────────────
log_info "[1/4] Criando infra/aks/environments/${CLIENT}.tfvars..."

cat > "infra/aks/environments/${CLIENT}.tfvars" <<EOF
# =============================================================================
# Cliente: ${CLIENT}
# Domínio: ${DOMAIN}
# DR: ${DR}
# Gerado por: scripts/new-client.sh em $(date +%Y-%m-%d)
# =============================================================================

environment         = "${CLIENT}"
resource_group_name = "sky-aks-${CLIENT}-rg"
aks_cluster_name    = "sky-aks-${CLIENT}"
dns_prefix          = "sky-${CLIENT}"
location            = "eastus2"

vnet_address_space  = ["${VNET_CIDR}"]
service_cidr        = "${SVC_CIDR}"

admin_username = "azureuser"

authorized_ips = [
  # TODO: Adicionar IPs do cliente e do time de DevOps
]

allowed_ssh_ips = [
  # TODO: Adicionar IPs autorizados para SSH
]

# =============================================================================
# Geo-Disaster Recovery
# =============================================================================
enable_geo_dr = ${DR}
EOF

if [[ "$DR" == "true" ]]; then
cat >> "infra/aks/environments/${CLIENT}.tfvars" <<EOF

dr_location            = "centralus"
dr_resource_group_name = "sky-aks-${CLIENT}-dr-rg"
dr_vnet_address_space  = "${DR_CIDR}"

dr_postgres_sku   = "GP_Standard_D2s_v3"
dr_redis_capacity = 1

# TODO: Preencher após terraform apply
dr_primary_origin_hostname   = "workspace.${DOMAIN}"
dr_secondary_origin_hostname = "workspace-dr.${DOMAIN}"
EOF
fi

log_ok "infra/aks/environments/${CLIENT}.tfvars criado"

# ─── 2. Criar estrutura de diretórios GitOps ──────────────────────────────────
log_info "[2/4] Criando estrutura GitOps..."

mkdir -p "gitops/bootstrap/clients/${CLIENT}/primary"
[[ "$DR" == "true" ]] && mkdir -p "gitops/bootstrap/clients/${CLIENT}/dr"

log_ok "Diretórios criados"

# ─── 3. Criar ArgoCD Application files ───────────────────────────────────────
log_info "[3/4] Gerando ArgoCD Applications..."

# Função para gerar Application
generate_app() {
  local APP_TYPE="$1"  # be, fe, ai, ai-worker
  local ENV_TYPE="$2"  # primary, dr
  local OUTPUT_FILE="gitops/bootstrap/clients/${CLIENT}/${ENV_TYPE}/${APP_TYPE/be/backend}.yaml"
  OUTPUT_FILE="${OUTPUT_FILE/ai-worker/ai-worker}"

  local APP_NAME_SUFFIX=""
  local IMAGE_NAME=""
  local TARGET_PORT=""
  local NAMESPACE_LABEL=""
  local SECRET_STORE="azure-keyvault"
  local MIGRATION_ENABLED="false"
  local DOMAIN_PREFIX="workspace"

  case "$APP_TYPE" in
    be)
      OUTPUT_FILE="gitops/bootstrap/clients/${CLIENT}/${ENV_TYPE}/backend.yaml"
      IMAGE_NAME="sky-poc-backend"; TARGET_PORT="8000"
      MIGRATION_ENABLED="true"; DOMAIN_PREFIX="api"
      ;;
    fe)
      OUTPUT_FILE="gitops/bootstrap/clients/${CLIENT}/${ENV_TYPE}/frontend.yaml"
      IMAGE_NAME="sky-poc-frontend"; TARGET_PORT="3000"
      DOMAIN_PREFIX="workspace"
      ;;
    ai)
      OUTPUT_FILE="gitops/bootstrap/clients/${CLIENT}/${ENV_TYPE}/ai.yaml"
      IMAGE_NAME="sky-poc-ai"; TARGET_PORT="8001"
      DOMAIN_PREFIX="ai"
      ;;
    ai-worker)
      OUTPUT_FILE="gitops/bootstrap/clients/${CLIENT}/${ENV_TYPE}/ai-worker.yaml"
      IMAGE_NAME="sky-poc-backend"; TARGET_PORT=""
      ;;
  esac

  local APP_SUFFIX=""
  local HOST_SUFFIX=""
  local KV_SUFFIX=""
  if [[ "$ENV_TYPE" == "dr" ]]; then
    APP_SUFFIX="-dr"
    HOST_SUFFIX="-dr"
    KV_SUFFIX="-dr"
    SECRET_STORE="azure-keyvault-dr"
    MIGRATION_ENABLED="false"
  fi

  local APP_FULL_NAME="sky-${APP_TYPE/be/be}-${CLIENT}${APP_SUFFIX}"
  APP_FULL_NAME="${APP_FULL_NAME/sky-ai-worker/sky-ai-worker}"

  local HOST="${DOMAIN_PREFIX}${HOST_SUFFIX}.${DOMAIN}"

  cat > "$OUTPUT_FILE" <<YAML
# Generated by scripts/new-client.sh — $(date +%Y-%m-%d)
# Client: ${CLIENT} | Type: ${APP_TYPE} | Env: ${ENV_TYPE}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: sky-${APP_TYPE}-${CLIENT}${APP_SUFFIX}
  namespace: argocd
$(if [[ "$ENV_TYPE" == "primary" && "$APP_TYPE" != "" ]]; then cat <<ANNOTATIONS
  annotations:
    argocd-image-updater.argoproj.io/image-list: ${IMAGE_NAME}=${ACR}.azurecr.io/${IMAGE_NAME}:^sha-.*
    argocd-image-updater.argoproj.io/sky-poc-${APP_TYPE/ai-worker/backend}.update-strategy: latest
    argocd-image-updater.argoproj.io/write-back-method: git:secret:argocd/git-creds
    argocd-image-updater.argoproj.io/write-back-target: branch:staging://gitops/charts/common-app/values-${CLIENT}-${APP_TYPE}.yaml
ANNOTATIONS
fi)
spec:
  project: default
  source:
    repoURL: "https://github.com/sky-first/sky-poc-infra.git"
    path: gitops/charts/common-app
    targetRevision: staging
    helm:
      valueFiles:
        - values-${CLIENT}-${APP_TYPE}${APP_SUFFIX}.yaml
      values: |
        nameOverride: "sky-${APP_TYPE}-${CLIENT}${APP_SUFFIX}"
        imagePullSecrets:
          - name: regcred
        externalSecret:
          enabled: true
          secretStoreRef:
            name: ${SECRET_STORE}
            kind: ClusterSecretStore
          target:
            creationPolicy: Owner
            name: sky-${APP_TYPE}-${CLIENT}${APP_SUFFIX}-secrets
  destination:
    server: "https://kubernetes.default.svc"
    namespace: ${CLIENT}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
YAML
}

# Gerar apps para primary
for app in be fe ai ai-worker; do
  generate_app "$app" "primary"
done
log_ok "Primary Applications geradas"

# Gerar apps para DR (se ativado)
if [[ "$DR" == "true" ]]; then
  for app in be fe ai ai-worker; do
    generate_app "$app" "dr"
  done
  log_ok "DR Applications geradas"
fi

# ─── 4. Criar values files ────────────────────────────────────────────────────
log_info "[4/4] Criando values files..."

for app in be fe ai ai-worker; do
  local_image="sky-poc-backend"
  [[ "$app" == "fe" ]] && local_image="sky-poc-frontend"
  [[ "$app" == "ai" ]] && local_image="sky-poc-ai"

  # Primary
  cat > "gitops/charts/common-app/values-${CLIENT}-${app}.yaml" <<EOF
# Managed by argocd-image-updater — não editar tag manualmente
image:
  repository: "${ACR}.azurecr.io/${local_image}"
  tag: "sha-latest"
  pullPolicy: IfNotPresent
EOF

  # DR (se ativado)
  if [[ "$DR" == "true" ]]; then
    cat > "gitops/charts/common-app/values-${CLIENT}-${app}-dr.yaml" <<EOF
# DR values — imagem fixada (image-updater não roda no cluster DR)
# Atualizar tag ao sincronizar com o primary
image:
  repository: "${ACR}.azurecr.io/${local_image}"
  tag: "sha-latest"
  pullPolicy: IfNotPresent
EOF
  fi
done

log_ok "Values files criados"

# ─── Resumo final ─────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              Onboarding Concluído!                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Arquivos criados:"
find "infra/aks/environments/${CLIENT}.tfvars" \
     "gitops/bootstrap/clients/${CLIENT}" \
     "gitops/charts/common-app" -name "*${CLIENT}*" 2>/dev/null | sort | sed 's/^/  ✓ /'

echo ""
echo -e "${YELLOW}Próximos passos:${NC}"
echo "  1. Revise os CIDRs em infra/aks/environments/${CLIENT}.tfvars"
echo "     (garantir que não conflitam com outros clientes)"
echo ""
echo "  2. Commit das mudanças:"
echo "     git add ."
echo "     git commit -m 'feat(clients): onboarding ${CLIENT}'"
echo "     git push"
echo ""
echo "  3. Provisionar infraestrutura:"
echo "     cd infra/aks"
echo "     terraform init -backend-config=... -backend-config=key=${CLIENT}.tfstate"
echo "     terraform apply -var-file=environments/${CLIENT}.tfvars"
echo ""
echo "  4. Após apply, atualizar o ACR e domínios nos arquivos de bootstrap"
echo "     (substituir BANCO_X_ACR pelo nome real do ACR criado)"
echo ""
if [[ "$DR" == "true" ]]; then
echo "  5. DR ativado — preencher após terraform apply:"
echo "     dr_primary_origin_hostname   em environments/${CLIENT}.tfvars"
echo "     dr_secondary_origin_hostname em environments/${CLIENT}.tfvars"
echo ""
fi
echo "  Documentação: docs/runbooks/new-client-onboarding.md"
echo ""
