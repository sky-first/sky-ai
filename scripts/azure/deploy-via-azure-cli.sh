#!/bin/bash
# Deploy via Azure CLI Run Command (não requer SSH direto)

set -eu

RESOURCE_GROUP="${RESOURCE_GROUP:-POC-SKY}"
VM_NAME="${VM_NAME:-poc-sky}"
BRANCH="${BRANCH:-main}"
REPO_OWNER="${REPO_OWNER:-sky-first}"
GH_PAT="${GH_PAT:-}"

echo "=========================================="
echo " Deploy via Azure CLI Run Command"
echo "=========================================="
echo ""
echo "Resource Group: $RESOURCE_GROUP"
echo "VM Name: $VM_NAME"
echo "Branch: $BRANCH"
echo "Repo Owner: $REPO_OWNER"
echo ""

# Verificar Azure CLI
if ! command -v az &> /dev/null; then
    echo "[ERROR] Azure CLI não está instalado"
    exit 1
fi

if ! az account show &> /dev/null; then
    echo "[ERROR] Não está autenticado. Execute: az login"
    exit 1
fi

echo "[OK] Azure CLI autenticado"
echo ""

# Script de deploy completo
read -r -d '' DEPLOY_SCRIPT << 'EOF' || true
set -eu

# Definir HOME se não estiver definido (necessário para Azure Run Command)
export HOME="${HOME:-/home/azureuser}"

PROJECT_DIR="/home/azureuser/projeto"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# Configurar Git com token se fornecido
if [ -n "${GH_PAT:-}" ]; then
    mkdir -p "$HOME/.git"
    git config --global credential.helper store
    echo "https://${GH_PAT}@github.com" > "$HOME/.git-credentials"
    chmod 600 "$HOME/.git-credentials"
fi

# Função para clonar ou atualizar repositório
clone_or_update() {
    local name=$1
    local url=$2
    local branch=${3:-main}
    
    if [ -d "$name/.git" ]; then
        echo "Atualizando $name..."
        cd "$name"
        git fetch origin
        git checkout -B "$branch" "origin/$branch" || git checkout "$branch" || true
        git pull origin "$branch" || true
        cd "$PROJECT_DIR"
    else
        echo "Clonando $name..."
        if [ -n "${GH_PAT:-}" ]; then
            # Usar token no URL
            url=$(echo "$url" | sed "s|https://github.com|https://${GH_PAT}@github.com|")
        fi
        git clone -b "$branch" "$url" "$name" || {
            echo "[WARNING]Falha ao clonar $name, tentando sem branch..."
            git clone "$url" "$name"
            cd "$name"
            git checkout "$branch" 2>/dev/null || true
            cd "$PROJECT_DIR"
        }
    fi
}

echo "=========================================="
echo "📦 Clonando/Atualizando Repositórios"
echo "=========================================="

clone_or_update "sky-poc-infra" "https://github.com/${REPO_OWNER}/sky-poc-infra.git" "staging"
clone_or_update "sky-poc-backend" "https://github.com/${REPO_OWNER}/sky-poc-backend.git" "staging"
clone_or_update "sky-poc-frontend" "https://github.com/${REPO_OWNER}/sky-poc-frontend.git" "staging"
clone_or_update "sky-poc-ai" "https://github.com/${REPO_OWNER}/sky-poc-ai.git" "staging"

echo ""
echo "=========================================="
echo " Configurando Ambiente"
echo "=========================================="

cd sky-poc-infra

# Verificar/criar .env
if [ ! -f .env ]; then
    if [ -f env.example ]; then
        echo "Criando .env a partir de env.example..."
        cp env.example .env
        echo "[WARNING]IMPORTANTE: Configure o arquivo .env antes de continuar!"
        echo "   Execute: nano .env"
        echo "   Ou edite via: az vm run-command invoke -g $RESOURCE_GROUP -n $VM_NAME --command-id RunShellScript --scripts 'nano /home/azureuser/projeto/sky-poc-infra/.env'"
    else
        echo "[ERROR] env.example não encontrado"
        exit 1
    fi
fi

# CRÍTICO: Validar configuração .env antes de continuar
echo ""
echo "=========================================="
echo "🔍 Validando Configuração .env"
echo "=========================================="
if [ -f scripts/validate-env.sh ]; then
    chmod +x scripts/validate-env.sh
    if ! bash scripts/validate-env.sh .env; then
        echo ""
        echo "[ERROR] ERRO: Validação do .env falhou!"
        echo "   Corrija os erros antes de continuar com o deploy."
        exit 1
    fi
else
    echo "[WARNING] Script de validação não encontrado (continuando sem validação)"
fi

# Configurar NEXT_PUBLIC_API_URL - CRÍTICO: Garantir que sempre esteja configurado
echo "=========================================="
echo " Configurando NEXT_PUBLIC_API_URL"
echo "=========================================="

VM_IP=$(curl -s http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01 -H "Metadata:true" 2>/dev/null || echo "")
if [ -z "$VM_IP" ]; then
    # Tentar obter IP público via Azure Metadata (método alternativo)
    VM_IP=$(curl -s -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | grep -oP '"publicIpAddress":"\K[^"]+' | head -1 || echo "")
fi

if [ -z "$VM_IP" ]; then
    echo "[ERROR] ERRO CRÍTICO: Não foi possível obter IP da VM"
    echo "   Tentando métodos alternativos..."
    
    # Tentar extrair de Terraform output se disponível
    if command -v terraform >/dev/null 2>&1 && [ -d infra/azure ]; then
        cd infra/azure
        VM_IP=$(terraform output -raw vm_public_ip 2>/dev/null || echo "")
        cd ../..
    fi
fi

if [ -n "$VM_IP" ]; then
    echo "[OK] IP da VM detectado: $VM_IP"
    
    # Sempre garantir que NEXT_PUBLIC_API_URL está correto
    if ! grep -q "^NEXT_PUBLIC_API_URL=" .env 2>/dev/null; then
        echo "NEXT_PUBLIC_API_URL=http://${VM_IP}/api/v1" >> .env
        echo "[OK] NEXT_PUBLIC_API_URL adicionado: http://${VM_IP}/api/v1"
    else
        # Atualizar se necessário
        CURRENT_URL=$(grep "^NEXT_PUBLIC_API_URL=" .env | cut -d'=' -f2- | tr -d '"' || echo "")
        EXPECTED_URL="http://${VM_IP}/api/v1"
        
        if [ "$CURRENT_URL" != "$EXPECTED_URL" ]; then
            sed -i "s|^NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=${EXPECTED_URL}|" .env
            echo "[OK] NEXT_PUBLIC_API_URL atualizado: ${EXPECTED_URL}"
        else
            echo "[OK] NEXT_PUBLIC_API_URL já está correto: ${EXPECTED_URL}"
        fi
    fi
else
    echo "[ERROR] ERRO CRÍTICO: Não foi possível obter IP da VM"
    echo "   Configure manualmente no .env: NEXT_PUBLIC_API_URL=http://<IP_DA_VM>/api/v1"
    exit 1
fi
echo ""

# Configurar CORS dinamicamente antes de iniciar containers
echo "=========================================="
echo " Configurando CORS Dinamicamente"
echo "=========================================="
if [ -f scripts/azure/fix-nginx-cors-dynamic.sh ]; then
    chmod +x scripts/azure/fix-nginx-cors-dynamic.sh
    bash scripts/azure/fix-nginx-cors-dynamic.sh || {
        echo "[WARNING] Aviso: Falha ao configurar CORS dinamicamente (continuando)"
    }
else
    echo "[WARNING] Script fix-nginx-cors-dynamic.sh não encontrado (CORS pode não funcionar corretamente)"
fi
echo ""

# Aplicar configuração nginx (HTTP-only se não houver certificados)
echo "=========================================="
echo " Aplicando Configuração Nginx"
echo "=========================================="
if [ -f scripts/azure/apply-nginx-config.sh ]; then
    chmod +x scripts/azure/apply-nginx-config.sh
    bash scripts/azure/apply-nginx-config.sh || {
        echo "[WARNING] Aviso: Falha ao aplicar configuração nginx (continuando)"
    }
else
    echo "[WARNING] Script apply-nginx-config.sh não encontrado"
fi
echo ""

echo "=========================================="
echo "🐳 Iniciando Containers"
echo "=========================================="

# Parar containers existentes
echo "Parando containers existentes..."
sudo docker compose down || sudo docker-compose down || true

# Build e start
echo "Construindo e iniciando containers..."
sudo docker compose up -d --build || {
    echo "[ERROR] Falha ao iniciar containers"
    echo "Logs:"
    sudo docker compose logs --tail=50
    exit 1
}

echo ""
echo "Aguardando containers iniciarem..."
sleep 15

echo ""
echo "=========================================="
echo "[OK] Status dos Containers"
echo "=========================================="
sudo docker compose ps

echo ""
echo "=========================================="
echo "📋 Logs do Proxy (últimas 20 linhas)"
echo "=========================================="
sudo docker compose logs proxy --tail=20 || sudo docker logs ai_saas_proxy --tail=20 2>/dev/null || echo "Proxy não encontrado"

echo ""
echo "=========================================="
echo "[OK] Deploy Concluído"
echo "=========================================="
EOF

# Preparar script com variáveis
# Definir variáveis no início do script
VAR_DEFS="export REPO_OWNER=\"$REPO_OWNER\"\nexport BRANCH=\"$BRANCH\"\nexport RESOURCE_GROUP=\"$RESOURCE_GROUP\"\nexport VM_NAME=\"$VM_NAME\"\n"
if [ -n "$GH_PAT" ]; then
    VAR_DEFS="${VAR_DEFS}export GH_PAT=\"$GH_PAT\"\n"
fi

FULL_SCRIPT=$(echo -e "$VAR_DEFS\n$DEPLOY_SCRIPT" | sed "s|\${REPO_OWNER}|\$REPO_OWNER|g" | sed "s|\${BRANCH}|\$BRANCH|g" | sed "s|\${RESOURCE_GROUP}|\$RESOURCE_GROUP|g" | sed "s|\${VM_NAME}|\$VM_NAME|g" | sed "s|\${GH_PAT:-}|\${GH_PAT:-}|g")

# Converter para array
IFS=$'\n' read -d '' -r -a SCRIPTS_ARRAY <<< "$FULL_SCRIPT" || true

echo "Executando deploy na VM..."
echo ""

OUTPUT=$(az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "${SCRIPTS_ARRAY[@]}" \
    --output json 2>&1)

if [ $? -eq 0 ]; then
    echo "=========================================="
    echo "[OK] Deploy executado"
    echo "=========================================="
    echo ""
    
    # Mostrar output
    echo "$OUTPUT" | jq -r '.value[0].message' 2>/dev/null || echo "$OUTPUT"
    
    echo ""
    echo "=========================================="
    echo "📋 Próximos Passos"
    echo "=========================================="
    echo ""
    echo "1. Verificar se containers estão rodando:"
    echo "   az vm run-command invoke -g $RESOURCE_GROUP -n $VM_NAME --command-id RunShellScript --scripts 'sudo docker ps'"
    echo ""
    echo "2. Se necessário, configurar .env:"
    echo "   az vm run-command invoke -g $RESOURCE_GROUP -n $VM_NAME --command-id RunShellScript --scripts 'cd /home/azureuser/projeto/sky-poc-infra && cat .env'"
    echo ""
    echo "3. Testar conexão:"
    echo "   curl http://172.172.134.36/health"
    echo ""
else
    echo "[ERROR] ERRO ao executar deploy"
    echo "$OUTPUT"
    exit 1
fi

