#!/usr/bin/env bash

# Backup do PostgreSQL (pg_dump) para Azure Blob Storage.
# Requer: az CLI autenticado (az login) e variáveis de ambiente:
#   STORAGE_ACCOUNT      - nome da Storage Account
#   STORAGE_CONTAINER    - nome do container de blobs
#   STORAGE_SAS_TOKEN    - SAS token (forma recomendada) OU AZURE_STORAGE_KEY
#   POSTGRES_CONTAINER   - nome do container Postgres (default: ai_saas_postgres_prod)
#   POSTGRES_DB          - nome do banco (default: ai_saas_db)
#   POSTGRES_USER        - usuário (default: postgres)
#
# Uso:
#   export STORAGE_ACCOUNT=...
#   export STORAGE_CONTAINER=...
#   export STORAGE_SAS_TOKEN="?sv=..."
#   cd /caminho/para/poc-deploy
#   ./scripts/postgres/backup_to_azure.sh
#
set -euo pipefail

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-ai_saas_postgres_prod}"
POSTGRES_DB="${POSTGRES_DB:-ai_saas_db}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"

if ! command -v az >/dev/null 2>&1; then
  echo "az CLI não encontrada. Instale e faça 'az login'."
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${POSTGRES_CONTAINER}$"; then
  echo "Container ${POSTGRES_CONTAINER} não está rodando."
  exit 1
fi

if [[ -z "${STORAGE_ACCOUNT:-}" || -z "${STORAGE_CONTAINER:-}" ]]; then
  echo "Defina STORAGE_ACCOUNT e STORAGE_CONTAINER."
  exit 1
fi

if [[ -z "${STORAGE_SAS_TOKEN:-}" && -z "${AZURE_STORAGE_KEY:-}" ]]; then
  echo "Defina STORAGE_SAS_TOKEN (recomendado) ou AZURE_STORAGE_KEY."
  exit 1
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_NAME="pgdump-${POSTGRES_DB}-${TS}.sql.gz"
BACKUP_PATH="/tmp/${BACKUP_NAME}"

echo "Gerando dump do banco ${POSTGRES_DB} a partir do container ${POSTGRES_CONTAINER}..."
docker exec "${POSTGRES_CONTAINER}" pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" | gzip > "${BACKUP_PATH}"
echo "Dump salvo em ${BACKUP_PATH} (tamanho: $(du -h "${BACKUP_PATH}" | cut -f1))."

AZ_ARGS=(
  storage blob upload
  --account-name "${STORAGE_ACCOUNT}"
  --container-name "${STORAGE_CONTAINER}"
  --file "${BACKUP_PATH}"
  --name "backups/${BACKUP_NAME}"
  --content-type "application/gzip"
  --no-progress
)

if [[ -n "${STORAGE_SAS_TOKEN:-}" ]]; then
  AZ_ARGS+=(--sas-token "${STORAGE_SAS_TOKEN}")
fi

echo "Enviando para Azure Blob Storage (container: ${STORAGE_CONTAINER})..."
az "${AZ_ARGS[@]}"

echo "Upload concluído: backups/${BACKUP_NAME}"
rm -f "${BACKUP_PATH}"
echo "Backup finalizado."


