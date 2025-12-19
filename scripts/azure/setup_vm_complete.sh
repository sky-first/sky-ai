#!/bin/bash

# Script completo para configurar a VM do Azure
# Execute este script dentro da VM após conectar via SSH

set -e

echo "Configuração Completa da VM Azure"
echo "======================================"
echo ""

# 1. Instalar Docker e dependências
echo "1⃣ Instalando Docker e dependências..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg lsb-release git

if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
fi

sudo usermod -aG docker $USER
sudo apt install -y docker-compose-plugin

echo "Docker instalado"
echo "Execute 'newgrp docker' para aplicar permissões"
echo ""

# 2. Criar estrutura de diretórios
echo "2⃣ Criando estrutura de diretórios..."
mkdir -p ~/projeto/poc-deploy
cd ~/projeto/poc-deploy

echo "Diretório criado: ~/projeto/poc-deploy"
echo ""

# 3. Instruções para copiar arquivos
echo "3⃣ Próximos passos:"
echo ""
echo "Você precisa copiar os arquivos do projeto para a VM."
echo "Opções:"
echo ""
echo "Opção A - Usar o script de deploy (do seu computador local):"
echo "cd /caminho/para/poc-deploy"
echo "./scripts/azure/deploy_to_vm.sh"
echo ""
echo "Opção B - Copiar manualmente via SCP (do seu computador local):"
echo "scp -i keys/azure/id_rsa -r \\"
echo "docker-compose*.yml env.example docker/ scripts/ \\"
echo "azureuser@172.191.77.30:~/projeto/poc-deploy/"
echo ""
echo "Opção C - Clonar do Git (se o repositório estiver no Git):"
echo "cd ~/projeto"
echo "git clone <URL_DO_REPOSITORIO> poc-deploy"
echo ""
echo "4⃣ Depois de copiar os arquivos, execute:"
echo "cd ~/projeto/poc-deploy"
echo "cp env.example .env"
echo "nano .env  # Configure as variáveis"
echo "newgrp docker  # Aplicar permissões Docker"
echo "docker compose -f docker-compose.postgres-only.yml up -d"
echo ""



