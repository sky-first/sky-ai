#!/bin/bash
# Script para fazer login no Azure e inicializar Terraform localmente
# Uso: ./scripts/setup-terraform-local.sh

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$PROJECT_DIR/infra/azure"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=========================================="
echo "🔐 Setup Terraform Local"
echo "=========================================="
echo ""

# 1. Verificar Azure CLI
echo "1.  Verificando Azure CLI..."
if ! command -v az >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Azure CLI não encontrado${NC}"
    echo "Instale com: brew install azure-cli"
    exit 1
fi
echo -e "${GREEN}[OK] Azure CLI encontrado${NC}"
echo ""

# 2. Verificar se está autenticado
echo "2.  Verificando autenticação Azure..."
if az account show >/dev/null 2>&1; then
    echo -e "${GREEN}[OK] Já autenticado no Azure${NC}"
    ACCOUNT=$(az account show --query "{Name:name, SubscriptionId:id}" -o tsv 2>/dev/null || echo "")
    if [ -n "$ACCOUNT" ]; then
        echo "   Conta: $(echo "$ACCOUNT" | head -1)"
        echo "   Subscription ID: $(echo "$ACCOUNT" | tail -1)"
    fi
else
    echo -e "${YELLOW}[WARNING] Não autenticado. Fazendo login...${NC}"
    echo ""
    echo "Isso abrirá seu navegador para autenticação."
    echo "Aguarde..."
    echo ""
    
    if az login --use-device-code >/dev/null 2>&1; then
        echo -e "${GREEN}[OK] Login realizado com sucesso${NC}"
    else
        echo -e "${YELLOW}[WARNING] Tentando login interativo...${NC}"
        az login || {
            echo -e "${RED}[ERROR] Falha ao fazer login no Azure${NC}"
            exit 1
        }
    fi
    
    # Mostrar conta atual
    ACCOUNT=$(az account show --query "{Name:name, SubscriptionId:id}" -o tsv 2>/dev/null || echo "")
    if [ -n "$ACCOUNT" ]; then
        echo "   Conta: $(echo "$ACCOUNT" | head -1)"
        echo "   Subscription ID: $(echo "$ACCOUNT" | tail -1)"
    fi
fi
echo ""

# 3. Verificar Terraform
echo "3.  Verificando Terraform..."
if ! command -v terraform >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Terraform não encontrado${NC}"
    echo "Instale com: brew install terraform"
    exit 1
fi
TERRAFORM_VERSION=$(terraform version -json 2>/dev/null | grep -o '"terraform_version":"[^"]*"' | cut -d'"' -f4 || terraform version | head -1)
echo -e "${GREEN}[OK] Terraform encontrado: $TERRAFORM_VERSION${NC}"
echo ""

# 4. Navegar para diretório do Terraform
echo "4.  Navegando para diretório do Terraform..."
cd "$TF_DIR" || {
    echo -e "${RED}[ERROR] Diretório do Terraform não encontrado: $TF_DIR${NC}"
    exit 1
}
echo -e "${GREEN}[OK] Diretório: $(pwd)${NC}"
echo ""

# 5. Verificar workspace
echo "5.  Verificando workspace Terraform..."
CURRENT_WORKSPACE=$(terraform workspace show 2>/dev/null || echo "default")
echo "   Workspace atual: $CURRENT_WORKSPACE"

# Listar workspaces disponíveis
echo "   Workspaces disponíveis:"
terraform workspace list 2>/dev/null || echo "   (nenhum workspace encontrado - será criado no init)"
echo ""

# 6. Verificar se precisa de backend config
echo "6.  Verificando configuração do backend..."
if [ -f "backend.hcl" ]; then
    echo -e "${GREEN}[OK] Arquivo backend.hcl encontrado${NC}"
    echo "   Usando: backend.hcl"
    BACKEND_CONFIG="-backend-config=backend.hcl"
elif [ -n "${TF_BACKEND_RESOURCE_GROUP:-}" ] && [ -n "${TF_BACKEND_STORAGE_ACCOUNT:-}" ]; then
    echo -e "${YELLOW}[WARNING] Variáveis de backend encontradas, criando backend.hcl...${NC}"
    cat > backend.hcl << EOF
resource_group_name  = "${TF_BACKEND_RESOURCE_GROUP}"
storage_account_name = "${TF_BACKEND_STORAGE_ACCOUNT}"
container_name       = "${TF_BACKEND_CONTAINER:-tfstate}"
key                  = "${TF_BACKEND_KEY_PREFIX:-poc-deploy}-${CURRENT_WORKSPACE}.tfstate"
use_azuread_auth     = true
EOF
    BACKEND_CONFIG="-backend-config=backend.hcl"
    echo -e "${GREEN}[OK] backend.hcl criado${NC}"
else
    echo -e "${YELLOW}[WARNING] Backend remoto não configurado${NC}"
    echo "   Usando backend local (terraform.tfstate)"
    echo ""
    echo "   Para usar backend remoto, configure:"
    echo "   - TF_BACKEND_RESOURCE_GROUP"
    echo "   - TF_BACKEND_STORAGE_ACCOUNT"
    echo "   - TF_BACKEND_CONTAINER"
    echo "   - TF_BACKEND_KEY_PREFIX"
    echo ""
    echo "   Ou crie um arquivo backend.hcl manualmente"
    BACKEND_CONFIG=""
fi
echo ""

# 7. Inicializar Terraform
echo "7.  Inicializando Terraform..."
if [ -n "$BACKEND_CONFIG" ]; then
    echo "   Comando: terraform init $BACKEND_CONFIG"
    terraform init -input=false $BACKEND_CONFIG || {
        echo -e "${RED}[ERROR] Falha ao inicializar Terraform${NC}"
        echo ""
        echo "Possíveis causas:"
        echo "  1. Storage Account não existe ou não tem acesso"
        echo "  2. Container não existe"
        echo "  3. Permissões insuficientes"
        echo ""
        echo "Tentando inicializar sem backend remoto..."
        terraform init -input=false -reconfigure || {
            echo -e "${RED}[ERROR] Falha ao inicializar Terraform mesmo sem backend${NC}"
            exit 1
        }
        echo -e "${YELLOW}[WARNING] Terraform inicializado sem backend remoto${NC}"
    }
else
    echo "   Comando: terraform init"
    terraform init -input=false || {
        echo -e "${RED}[ERROR] Falha ao inicializar Terraform${NC}"
        exit 1
    }
fi
echo -e "${GREEN}[OK] Terraform inicializado${NC}"
echo ""

# 8. Verificar se consegue obter outputs
echo "8.  Verificando acesso ao estado..."
if terraform output vm_public_ip >/dev/null 2>&1; then
    VM_IP=$(terraform output -raw vm_public_ip 2>/dev/null || echo "")
    if [ -n "$VM_IP" ]; then
        echo -e "${GREEN}[OK] IP da VM obtido: $VM_IP${NC}"
    else
        echo -e "${YELLOW}[WARNING] Estado não tem vm_public_ip ainda${NC}"
    fi
else
    echo -e "${YELLOW}[WARNING] Não foi possível acessar outputs (pode ser normal se ainda não fez apply)${NC}"
fi
echo ""

# 9. Resumo
echo "=========================================="
echo "[OK] Setup Concluído"
echo "=========================================="
echo ""
echo "Próximos passos:"
echo "  1. Selecionar workspace (se necessário):"
echo "     terraform workspace select <workspace>"
echo ""
echo "  2. Verificar plan:"
echo "     terraform plan -var-file=terraform.tfvars.<ambiente>"
echo ""
echo "  3. Obter IP da VM:"
echo "     terraform output vm_public_ip"
echo ""
echo "  4. Executar verificação de login:"
echo "     cd $PROJECT_DIR"
echo "     ./scripts/verify-login-complete.sh <IP_DA_VM>"
echo ""

