#!/bin/bash
# scripts/fix-env-secrets.sh
# Atualiza .env com senhas seguras se ainda tiver placeholders

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Arquivo .env não encontrado"
    echo "Crie a partir de env.example: cp env.example .env"
    exit 1
fi

echo "🔐 Gerando senhas seguras e atualizando .env..."

# Gerar senhas
POSTGRES_PASS=$(openssl rand -base64 32)
REDIS_PASS=$(openssl rand -base64 32)
JWT_SECRET=$(openssl rand -hex 32)
ENCRYPTION_KEY=$(openssl rand -hex 32)

# Detectar sistema operacional para usar sed correto
if [[ "$OSTYPE" == "darwin"* ]]; then
    SED_CMD="sed -i ''"
else
    SED_CMD="sed -i"
fi

# Atualizar apenas se tiver placeholder
if grep -q "POSTGRES_PASSWORD=secure_password_here\|POSTGRES_PASSWORD=generate" "$ENV_FILE"; then
    $SED_CMD "s|POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$POSTGRES_PASS|g" "$ENV_FILE"
    echo "✅ POSTGRES_PASSWORD atualizado"
fi

if grep -q "REDIS_PASSWORD=secure_redis_password_here\|REDIS_PASSWORD=generate" "$ENV_FILE"; then
    $SED_CMD "s|REDIS_PASSWORD=.*|REDIS_PASSWORD=$REDIS_PASS|g" "$ENV_FILE"
    echo "✅ REDIS_PASSWORD atualizado"
fi

if grep -q "JWT_SECRET_KEY=generate_a_secure\|JWT_SECRET_KEY=generate" "$ENV_FILE"; then
    $SED_CMD "s|JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$JWT_SECRET|g" "$ENV_FILE"
    echo "✅ JWT_SECRET_KEY atualizado"
fi

if grep -q "ENCRYPTION_KEY=generate_another\|ENCRYPTION_KEY=generate" "$ENV_FILE"; then
    $SED_CMD "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENCRYPTION_KEY|g" "$ENV_FILE"
    echo "✅ ENCRYPTION_KEY atualizado"
fi

# Garantir permissões corretas
chmod 600 "$ENV_FILE"

echo ""
echo "✅ .env atualizado com senhas seguras!"
echo "📝 Permissões ajustadas para 600"


