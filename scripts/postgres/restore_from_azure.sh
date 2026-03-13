#!/usr/bin/env bash

# ==============================================================================
# SRE RESTORE TOOL - Sky Platform
# Uso: ./restore_from_azure.sh --blob-name <NOME_DO_ARQUIVO> [--env staging]
# ==============================================================================

set -euo pipefail

ENVIRONMENT="${ENVIRONMENT:-prod}"
DB_HOST="postgresql"
DB_NAME="ai_saas_db"
DB_USER="sky"
STORAGE_ACCOUNT="skybkpprod8ooz9z"
CONTAINER_NAME="sql-backups"
BLOB_NAME=""

# Parsing argumentos
while [[ $# -gt 0 ]]; do
  case $1 in
    --blob-name) BLOB_NAME="$2"; shift 2 ;;
    --env) ENVIRONMENT="$2"; shift 2 ;;
    *) echo "Opção desconhecida: $1"; exit 1 ;;
  esac
done

if [[ -z "$BLOB_NAME" ]]; then
  echo "❌ ERRO: --blob-name é obrigatório."
  echo "Exemplo: ./restore_from_azure.sh --blob-name backup-ai_saas_db-20260311-020000.dump"
  exit 1
fi

echo "🚀 Iniciando processo de RESTORE para o ambiente: $ENVIRONMENT"
echo "📦 Blob: $BLOB_NAME"

# 1. Download do Backup
LOCAL_PATH="/tmp/restore-$(date +%s).dump"
echo "📥 Baixando backup da Azure..."
az storage blob download \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER_NAME" \
  --name "$BLOB_NAME" \
  --file "$LOCAL_PATH" \
  --auth-mode login

# 2. Validação básica do dump
if [[ ! -f "$LOCAL_PATH" ]]; then
  echo "❌ ERRO: Falha ao baixar o arquivo."
  exit 1
fi

# 3. Execução do Restore
echo "⚠️ ATENÇÃO: Isso irá limpar o banco de dados atual antes do restore!"
echo "Executando pg_restore..."

# Extraímos a senha do secret se disponível locally (simulação de permissão de admin)
export PGPASSWORD=${POSTGRES_PASSWORD:-""}

if [[ -z "$PGPASSWORD" ]]; then
    echo "🔍 PGPASSWORD não definida. Tentando via kubectl secret..."
    PGPASSWORD=$(kubectl get secret -n "$ENVIRONMENT" postgresql -o jsonpath="{.data.postgres-password}" | base64 --decode)
    export PGPASSWORD
fi

pg_restore -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" \
  --clean --if-exists --no-owner --no-privileges \
  -Fc "$LOCAL_PATH"

echo "✅ Restore concluído com sucesso!"
rm -f "$LOCAL_PATH"
