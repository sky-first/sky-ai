#!/bin/bash
set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}🔒 Iniciando correção de Terraform State Lock...${NC}"

# Verificar se o usuário está logado no Azure
if ! command -v az &> /dev/null; then
    echo -e "${RED}❌ Azure CLI não encontrado. Instale-o primeiro.${NC}"
    exit 1
fi

if ! az account show &> /dev/null; then
    echo -e "${RED}❌ Você precisa estar logado no Azure CLI. Rode 'az login' e tente novamente.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Azure Login detectado.${NC}"

# Navegar para o diretório correto
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
AKS_DIR="$PROJECT_ROOT/infra/aks"

if [ ! -d "$AKS_DIR" ]; then
    echo -e "${RED}❌ Diretório infra/aks não encontrado em $AKS_DIR${NC}"
    exit 1
fi

cd "$AKS_DIR"
echo -e "${YELLOW}📂 Entrando em infra/aks...${NC}"

echo -e "${YELLOW}🔄 Inicializando Terraform para configurar o backend...${NC}"
# Usamos -reconfigure e passamos o arquivo de config explicitamente
terraform init -reconfigure -backend-config=backend.hcl

LOCK_ID="b7d79bba-7d81-e259-1b59-a733049884b9"

echo -e "${YELLOW}🔓 Tentando remover o lock ID: ${LOCK_ID}...${NC}"
terraform force-unlock -force "$LOCK_ID"

echo -e "${GREEN}✅ Lock removido com sucesso!${NC}"
echo -e "${GREEN}🚀 Agora você pode re-executar o Pipeline no GitHub Actions.${NC}"
