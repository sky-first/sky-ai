#!/bin/bash
# Script para corrigir .env na VM usando sudo (quando necessário)
# Execute na VM

set -eu

cd ~/projeto/sky-poc-infra 2>/dev/null || cd ~/projeto/poc-deploy || {
    echo "❌ Diretório do projeto não encontrado"
    exit 1
}

ENV_FILE=".env"

echo "=========================================="
echo "🔧 Correção de .env (com sudo se necessário)"
echo "=========================================="
echo ""

# Verificar dono do arquivo
OWNER=$(stat -c '%U' "$ENV_FILE" 2>/dev/null || stat -f '%Su' "$ENV_FILE" 2>/dev/null || echo "unknown")
echo "Dono do arquivo: $OWNER"
echo "Usuário atual: $(whoami)"
echo ""

# Verificar permissões
PERMS=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%A' "$ENV_FILE" 2>/dev/null || echo "unknown")
echo "Permissões atuais: $PERMS"
echo ""

# Verificar valor atual
echo "Valor atual de NEXT_PUBLIC_API_URL:"
grep "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" 2>/dev/null || echo "  (não encontrado)"
echo ""

# Criar arquivo temporário com correção
TMP_FILE="/tmp/env_fixed_$$"
grep -v "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" > "$TMP_FILE" 2>/dev/null || {
    echo "❌ Erro ao ler .env"
    exit 1
}

# Adicionar valor correto
echo "NEXT_PUBLIC_API_URL=/api/v1" >> "$TMP_FILE"

# Copiar de volta (usando sudo se necessário)
if [ -w "$ENV_FILE" ]; then
    cp "$TMP_FILE" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "✅ Arquivo atualizado (sem sudo)"
else
    sudo cp "$TMP_FILE" "$ENV_FILE"
    sudo chmod 600 "$ENV_FILE"
    sudo chown $(whoami):$(whoami) "$ENV_FILE" 2>/dev/null || true
    echo "✅ Arquivo atualizado (com sudo)"
fi

# Limpar arquivo temporário
rm -f "$TMP_FILE"

echo ""
echo "✅ Correção aplicada!"
echo ""
echo "Novo valor:"
grep "^NEXT_PUBLIC_API_URL=" "$ENV_FILE"
echo ""
echo "Próximo passo:"
echo "  docker compose restart frontend"

