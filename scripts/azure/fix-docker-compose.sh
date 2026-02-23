#!/bin/bash
# Corrige docker-compose.yml para usar asyncpg e caminhos corretos
# Garante que configuração esteja sempre correta

set -eu

PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
cd "$PROJECT_DIR" || {
    if [ -d ~/projeto/sky-poc-infra ]; then
        cd ~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        cd ~/projeto/poc-deploy
    else
        echo "[ERROR] ERRO: Diretório do projeto não encontrado"
        exit 1
    fi
}

COMPOSE_FILE="docker-compose.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "[ERROR] ERRO: $COMPOSE_FILE não encontrado"
    exit 1
fi

echo "=========================================="
echo " Corrigindo docker-compose.yml"
echo "=========================================="
echo ""

# Backup
cp "$COMPOSE_FILE" "${COMPOSE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"

# 1. Corrigir DATABASE_URL para usar asyncpg
if grep -q "postgresql+psycopg2://" "$COMPOSE_FILE"; then
    sed -i "s|postgresql+psycopg2://|postgresql+asyncpg://|g" "$COMPOSE_FILE"
    sed -i "s|?sslmode=require||g" "$COMPOSE_FILE"
    echo "[OK] DATABASE_URL corrigido para asyncpg"
fi

# 2. Corrigir caminhos dos build contexts
if grep -q "context: ../backend" "$COMPOSE_FILE"; then
    sed -i "s|context: ../backend|context: ../sky-poc-backend|g" "$COMPOSE_FILE"
    echo "[OK] Build context do backend corrigido"
fi

if grep -q "context: ../frontend" "$COMPOSE_FILE"; then
    sed -i "s|context: ../frontend|context: ../sky-poc-frontend|g" "$COMPOSE_FILE"
    echo "[OK] Build context do frontend corrigido"
fi

if grep -q "context: ../ai" "$COMPOSE_FILE"; then
    sed -i "s|context: ../ai|context: ../sky-poc-ai|g" "$COMPOSE_FILE"
    echo "[OK] Build context do AI corrigido"
fi

# 3. Validar estrutura
echo ""
echo "Verificando estrutura..."
VALID=true

if [ ! -d "../sky-poc-backend" ]; then
    echo "[WARNING] ../sky-poc-backend não encontrado"
    VALID=false
fi

if [ ! -d "../sky-poc-frontend" ]; then
    echo "[WARNING] ../sky-poc-frontend não encontrado"
    VALID=false
fi

if [ ! -d "../sky-poc-ai" ]; then
    echo "[WARNING] ../sky-poc-ai não encontrado"
    VALID=false
fi

if [ "$VALID" = "true" ]; then
    echo "[OK] Todos os build contexts existem"
else
    echo "[WARNING] Alguns build contexts não existem (pode ser normal se ainda não clonou)"
fi

# 4. Validar docker-compose.yml
if docker compose config > /dev/null 2>&1; then
    echo "[OK] docker-compose.yml válido"
else
    echo "[ERROR] ERRO: docker-compose.yml inválido após correções"
    echo "Restaurando backup..."
    mv "${COMPOSE_FILE}.backup"* "$COMPOSE_FILE" 2>/dev/null || true
    exit 1
fi

echo ""
echo "=========================================="
echo "[OK] docker-compose.yml Corrigido"
echo "=========================================="

