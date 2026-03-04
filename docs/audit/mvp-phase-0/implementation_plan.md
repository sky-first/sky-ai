# Implementação de Correções para Auditoria MVP (Phase 0)

## Objetivo
Implementar a "Phase 0: Operational Survival" para garantir estabilidade e recuperação de desastres.

## User Review Required
> [!IMPORTANT]
> **Backup Storage**: O plano requer um Storage Account Azure. Iremos usar `azcopy` com SAS Token (mais simples para MVP) ou Workload Identity.
> **Downtime**: A aplicação de limites no Postgres causará um restart do pod (downtime de ~30s).

## Proposed Changes

### 1. Hardening do Banco de Dados (Resource Limits)
**Status:** ✅ COMPLETED
**Arquivo:** `gitops/manifests/databases/postgres.yaml`
**Ação:** Adicionar bloco `resources` ao container `postgres`.

```yaml
resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi
```

### 2. Infraestrutura de Backup (Azure)
**Status:** ✅ COMPLETED
**Ação:** Provisionar Azure Storage Account (se não existir).
- Resource Group: `sky-infra-backups-rg`
- Storage Account: `skyinfrabackups` (ou similar único)
- Container: `postgres-backups-staging`

### 3. Automação de Backup (CronJob)
**Status:** ✅ COMPLETED
**Novo Arquivo:** `gitops/manifests/databases/backup-cronjob.yaml`
**Spec Técnica:**
- **Schedule:** `0 3 * * *` (03:00 AM UTC diário).
- **Image:** `mcr.microsoft.com/azure-cli` (contém `az` e `pg_dump` pode ser instalado ou usar imagem custom).
- **Command:**
    1. `apk add postgresql-client` (se usar imagem alpine based).
    2. `pg_dump -h postgres -U postgres -d ai_saas_db | gzip > dump.sql.gz`
    3. `az storage blob upload -f dump.sql.gz -c postgres-backups-staging -n backup-$(date +%F).sql.gz --account-name ... --sas-token ...`
- **Secret:** `backup-secrets` contendo `SAS_TOKEN` ou usar Workload Identity.

## Verification Plan

### Automated Tests
1. [x] **Apply Manifests:** `kubectl apply -f gitops/manifests/databases/`
2. [x] **Verify Pod Restart:** `kubectl rollout status statefulset/postgres`
3. [x] **Trigger Backup:** `kubectl create job --from=cronjob/postgres-backup manual-test-01`
4. [x] **Verify Upload:** `az storage blob list --container-name postgres-backups-staging --output table`

### Manual Verification (Recovery Drill)
1. **Simulate Data Loss:** `kubectl exec -it postgres-0 -- psql -U postgres -d ai_saas_db -c "DROP TABLE some_critical_table;"`
2. **Restore:**
    - Download blob: `az storage blob download ...`
    - Restore: `gunzip -c dump.sql.gz | psql -h postgres -U postgres -d ai_saas_db`
3. **Validate:** Check if table exists again.
