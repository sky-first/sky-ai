#!/bin/bash

# Script para configurar o servidor Azure VM
# Execute este script dentro da VM após conectar via SSH

set -e  # Parar em caso de erro

echo "Configurando servidor Azure VM..."
echo ""

# 1. Atualizar sistema
echo "1⃣ Atualizando sistema..."
sudo apt update && sudo apt upgrade -y

# 2. Instalar dependências
echo ""
echo "2⃣ Instalando dependências..."
sudo apt install -y ca-certificates curl gnupg lsb-release git

# 3. Instalar Docker
echo ""
echo "3⃣ Instalando Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
    echo "Docker instalado"
else
    echo "Docker já está instalado"
fi

# 4. Adicionar usuário ao grupo docker
echo ""
echo "4⃣ Configurando permissões Docker..."
sudo usermod -aG docker $USER
echo "Usuário adicionado ao grupo docker"
echo "Você precisará relogar ou executar: newgrp docker"

# 5. Instalar Docker Compose
echo ""
echo "5⃣ Instalando Docker Compose..."
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    sudo apt install -y docker-compose-plugin
    echo "Docker Compose instalado"
else
    echo "Docker Compose já está instalado"
fi

# 6. Verificar instalações
echo ""
echo "6⃣ Verificando instalações..."
docker --version 2>/dev/null || echo "Docker não disponível (relogue para aplicar)"
docker compose version 2>/dev/null || echo "Docker Compose não disponível (relogue para aplicar)"

echo ""
echo "Configuração básica concluída!"
echo ""
echo "Próximos passos:"
echo "1. Relogue na VM (saia e entre novamente) OU execute: newgrp docker"
echo "2. Navegue para: cd ~/projeto/poc-deploy"
echo "3. Configure o .env: cp env.example .env && nano .env"
echo "4. Inicie PostgreSQL: docker compose -f docker-compose.postgres-only.yml up -d"
echo ""



