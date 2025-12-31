#!/bin/bash

# Script para copiar o projeto poc-deploy para a VM do Azure
# Execute este script do seu computador local

set -eu

# Obter IP da VM automaticamente do Terraform
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/../../infra/azure"
VM_IP=$(cd "$TERRAFORM_DIR" && terraform output -raw vm_public_ip 2>/dev/null || echo "172.191.77.30")
VM_USER="azureuser"
SSH_KEY="keys/azure/id_rsa"
PROJECT_DIR="~/projeto"

echo "Copiando projeto poc-deploy para a VM Azure..."
echo "VM: $VM_USER@$VM_IP"
echo ""

# Verificar se a chave SSH existe
if [ ! -f "$SSH_KEY" ]; then
    echo "Chave SSH não encontrada: $SSH_KEY"
    exit 1
fi

# Verificar se está no diretório correto
if [ ! -f "docker-compose.postgres-only.yml" ]; then
    echo "Execute este script do diretório raiz do projeto poc-deploy"
    exit 1
fi

echo "1⃣ Criando diretório na VM..."
ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "mkdir -p $PROJECT_DIR"

echo ""
echo "2⃣ Copiando arquivos do projeto..."
# Copiar apenas arquivos necessários (excluindo .git, node_modules, etc)
rsync -avz --progress \
    -e "ssh -i $SSH_KEY" \
    --exclude '.git' \
    --exclude 'node_modules' \
    --exclude '.env' \
    --exclude '*.tfstate*' \
    --exclude '.terraform' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache' \
    --exclude 'dist' \
    --exclude 'build' \
    ./ "$VM_USER@$VM_IP:$PROJECT_DIR/poc-deploy/"

echo ""
echo "3⃣ Criando arquivo .env na VM..."
# Copiar env.example como .env
ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" "cd $PROJECT_DIR/poc-deploy && cp env.example .env"

echo ""
echo "Projeto copiado com sucesso!"
echo ""
echo "Próximos passos na VM:"
echo "1. Conecte-se: ./access_server_azure.sh"
echo "2. Execute: cd ~/projeto/poc-deploy"
echo "3. Configure o .env: nano .env"
echo "4. Aplique grupo docker: newgrp docker"
echo "5. Inicie PostgreSQL: docker compose -f docker-compose.postgres-only.yml up -d"
echo ""



