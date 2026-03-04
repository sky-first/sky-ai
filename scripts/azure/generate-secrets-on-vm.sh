#!/bin/bash
# Script para gerar valores seguros no .env da VM
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

if [ ! -f .env ]; then
    echo "[ERROR] ERRO: Arquivo .env não encontrado em $INFRA_DIR"
    exit 1
fi

echo " Gerando valores seguros para variáveis com placeholders..."
echo ""

# Função para gerar senha segura
generate_password() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-32
}

# Função para gerar JWT secret (hex)
generate_jwt_secret() {
    openssl rand -hex 32
}

# Função para gerar encryption key (hex)
generate_encryption_key() {
    openssl rand -hex 32
}

# Atualizar apenas se tiver placeholder
UPDATED=false

# Função para atualizar variável no .env (usa cat para escrever diretamente)
update_env_var() {
    local var_name="$1"
    local old_value="$2"
    local new_value="$3"
    
    # Criar arquivo temporário em /tmp (sempre tem permissão de escrita)
    local tmp_file=$(mktemp /tmp/env_update.XXXXXX)
    
    # Substituir e salvar em arquivo temporário
    sed "s|${var_name}=${old_value}|${var_name}=${new_value}|g" .env > "$tmp_file"
    
    # Usar cat para escrever o conteúdo diretamente (evita problemas de mv)
    cat "$tmp_file" > .env
    
    # Remover arquivo temporário
    rm -f "$tmp_file"
    
    # Garantir permissões
    chmod 600 .env
}

# REDIS_PASSWORD
if grep -q "REDIS_PASSWORD=secure_redis_password_here" .env; then
    NEW_PASS=$(generate_password)
    update_env_var "REDIS_PASSWORD" "secure_redis_password_here" "$NEW_PASS"
    echo "[OK] REDIS_PASSWORD atualizado"
    UPDATED=true
fi

# JWT_SECRET_KEY
if grep -q "JWT_SECRET_KEY=generate_a_secure_random_string_here" .env; then
    NEW_SECRET=$(generate_jwt_secret)
    update_env_var "JWT_SECRET_KEY" "generate_a_secure_random_string_here" "$NEW_SECRET"
    echo "[OK] JWT_SECRET_KEY atualizado"
    UPDATED=true
fi

# ENCRYPTION_KEY
if grep -q "ENCRYPTION_KEY=generate_another_secure_key_here" .env; then
    NEW_KEY=$(generate_encryption_key)
    update_env_var "ENCRYPTION_KEY" "generate_another_secure_key_here" "$NEW_KEY"
    echo "[OK] ENCRYPTION_KEY atualizado"
    UPDATED=true
fi

# Garantir permissões
chmod 600 .env

if [ "$UPDATED" = "true" ]; then
    echo ""
    echo "[OK] Variáveis atualizadas com valores seguros!"
    echo " Permissões ajustadas para 600"
    echo ""
    echo "[WARNING] IMPORTANTE: Reinicie os containers para aplicar as mudanças:"
    echo "   cd $INFRA_DIR"
    echo "   sudo docker compose restart"
else
    echo "ℹ  Nenhuma variável com placeholder encontrada"
    echo "   Todas as variáveis já estão configuradas"
fi

