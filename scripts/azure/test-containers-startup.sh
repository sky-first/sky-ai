#!/bin/bash
# Script para testar se os containers conseguem iniciar corretamente
# Pode ser executado via Azure CLI run-command ou diretamente na VM

set -euo pipefail

BASE="/home/azureuser/projeto"
if [ -d "$BASE/sky-poc-infra" ]; then
    INFRA_DIR="$BASE/sky-poc-infra"
elif [ -d "$BASE/poc-deploy" ]; then
    INFRA_DIR="$BASE/poc-deploy"
else
    echo "[ERROR] ERRO: Diretório de infraestrutura não encontrado"
    exit 1
fi

cd "$INFRA_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo " Teste de Inicialização dos Containers"
echo "==========================================${NC}"
echo ""

# 1. Verificar docker compose
echo -e "${BLUE}1.  Verificando Docker Compose...${NC}"
if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Docker não está instalado${NC}"
    exit 1
fi

if ! sudo docker compose version >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] docker compose não está disponível${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] Docker Compose OK${NC}"
echo ""

# 2. Verificar .env
echo -e "${BLUE}2.  Verificando .env...${NC}"
if [ ! -f .env ]; then
    echo -e "${RED}[ERROR] .env não encontrado${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] .env encontrado${NC}"
echo ""

# 3. Verificar docker-compose.yml
echo -e "${BLUE}3.  Verificando docker-compose.yml...${NC}"
if [ ! -f docker-compose.yml ]; then
    echo -e "${RED}[ERROR] docker-compose.yml não encontrado${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] docker-compose.yml encontrado${NC}"
echo ""

# 4. Testar validação do docker-compose
echo -e "${BLUE}4.  Validando docker-compose.yml...${NC}"
if ! sudo docker compose config >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] docker-compose.yml tem erros de sintaxe${NC}"
    sudo docker compose config 2>&1 | head -20
    exit 1
fi
echo -e "${GREEN}[OK] docker-compose.yml válido${NC}"
echo ""

# 5. Verificar se containers podem ser criados (dry-run)
echo -e "${BLUE}5.  Testando criação de containers (dry-run)...${NC}"
if ! sudo docker compose up --dry-run >/dev/null 2>&1; then
    echo -e "${YELLOW}[WARNING] Dry-run não disponível (continuando...)${NC}"
else
    echo -e "${GREEN}[OK] Containers podem ser criados${NC}"
fi
echo ""

# 6. Verificar recursos disponíveis
echo -e "${BLUE}6.  Verificando recursos disponíveis...${NC}"
TOTAL_MEM=$(free -m | awk '/^Mem:/{print $2}')
AVAILABLE_MEM=$(free -m | awk '/^Mem:/{print $7}')
echo "Memória total: ${TOTAL_MEM}MB"
echo "Memória disponível: ${AVAILABLE_MEM}MB"

if [ "$AVAILABLE_MEM" -lt 2048 ]; then
    echo -e "${YELLOW}[WARNING] Pouca memória disponível (recomendado: 2GB+)${NC}"
else
    echo -e "${GREEN}[OK] Memória suficiente${NC}"
fi
echo ""

# 7. Verificar espaço em disco
echo -e "${BLUE}7.  Verificando espaço em disco...${NC}"
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
echo "Uso do disco: ${DISK_USAGE}%"

if [ "$DISK_USAGE" -gt 90 ]; then
    echo -e "${RED}[ERROR] Disco quase cheio (${DISK_USAGE}%)${NC}"
    exit 1
elif [ "$DISK_USAGE" -gt 80 ]; then
    echo -e "${YELLOW}[WARNING] Disco com pouco espaço (${DISK_USAGE}%)${NC}"
else
    echo -e "${GREEN}[OK] Espaço em disco OK${NC}"
fi
echo ""

echo -e "${GREEN}=========================================="
echo "[OK] Todos os pré-requisitos estão OK!"
echo "==========================================${NC}"
echo ""
echo "Próximo passo: Execute o deploy sequencial:"
echo "  bash scripts/azure/sequential-deploy.sh"

