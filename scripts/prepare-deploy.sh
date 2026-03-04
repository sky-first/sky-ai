#!/bin/bash
# scripts/prepare-deploy.sh
# Script helper para configurar variáveis e executar deploy
# Evita problemas com comentários inline no terminal

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cores
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════╗"
echo "║     Preparar Deploy Local na VM                    ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Verificar se VM_IP já está configurado
if [ -z "${VM_IP:-}" ]; then
    echo ""
    echo "Digite o IP da VM (ou pressione Enter para usar padrão: 172.191.77.30):"
    read -r VM_IP_INPUT
    if [ -z "$VM_IP_INPUT" ]; then
        export VM_IP=172.191.77.30
    else
        export VM_IP="$VM_IP_INPUT"
    fi
fi

# Verificar se BRANCH já está configurado
if [ -z "${BRANCH:-}" ]; then
    echo ""
    echo "Digite a branch (ou pressione Enter para usar padrão: staging):"
    read -r BRANCH_INPUT
    if [ -z "$BRANCH_INPUT" ]; then
        export BRANCH=staging
    else
        export BRANCH="$BRANCH_INPUT"
    fi
fi

# Verificar se GH_PAT está configurado
if [ -z "${GH_PAT:-}" ]; then
    echo ""
    echo "Se os repositórios forem privados, digite o GH_PAT (ou pressione Enter para pular):"
    read -r GH_PAT_INPUT
    if [ -n "$GH_PAT_INPUT" ]; then
        export GH_PAT="$GH_PAT_INPUT"
    fi
fi

echo ""
echo -e "${GREEN}✅ Variáveis configuradas:${NC}"
echo "  VM_IP: $VM_IP"
echo "  BRANCH: $BRANCH"
if [ -n "${GH_PAT:-}" ]; then
    echo "  GH_PAT: ${GH_PAT:0:10}... (configurado)"
else
    echo -e "  GH_PAT: ${YELLOW}não configurado${NC} (opcional)"
fi

echo ""
echo "Deseja executar o deploy agora? (s/n)"
read -r CONFIRM

if [ "$CONFIRM" != "s" ] && [ "$CONFIRM" != "S" ] && [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo ""
    echo "Variáveis configuradas! Execute manualmente:"
    echo "  ./scripts/deploy-local-to-vm.sh"
    echo ""
    echo "Ou exporte as variáveis:"
    echo "  export VM_IP=$VM_IP"
    echo "  export BRANCH=$BRANCH"
    if [ -n "${GH_PAT:-}" ]; then
        echo "  export GH_PAT=$GH_PAT"
    fi
    exit 0
fi

echo ""
echo "🚀 Executando deploy..."
echo ""

cd "$PROJECT_DIR"
./scripts/deploy-local-to-vm.sh


