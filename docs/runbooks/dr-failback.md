# Sky DR Failback Runbook
**Ticket:** DO2025-1044  
**Pré-requisito:** Failover concluído ([dr-failover.md](./dr-failover.md))  
**Janela recomendada:** Horário de baixo tráfego (madrugada)

---

## Objetivo

Retornar a operação para a região primária (eastus2) após a estabilização do incidente.

> **Regra de ouro:** Só executar failback quando a região primária estiver 100% estável
> por pelo menos **2 horas seguidas** sem alertas ativos.

---

## Fase 1 — Validar Região Primária (0-15 min)

```bash
# Verificar status da Azure eastus2
az rest --method GET \
  --url "https://management.azure.com/subscriptions/<SUB_ID>/providers/Microsoft.ResourceHealth/availabilityStatuses?api-version=2022-10-01&$filter=Location eq 'eastus2'" \
  --query "value[0].properties.availabilityState" -o tsv
# Esperado: "Available"

# Verificar cluster primary
kubectl get nodes --context sky-aks-vip --timeout=30s

# Verificar PostgreSQL (agora standalone após failover)
az postgres flexible-server show \
  --name sky-postgres-prod-vip-primary \
  --resource-group sky-aks-vip-rg \
  --query "state" -o tsv
# Esperado: "Ready"
```

---

## Fase 2 — Re-sincronizar Dados (15-60 min)

> **IMPORTANTE:** Após o failover, a replica antiga (primary original) e o novo primary
> (replica promovida) são servidores independentes. Não há sincronização automática.
> Os dados escritos no DR durante o failover precisam ser migrados manualmente.

### 2a. Exportar dados do PostgreSQL DR

```bash
DR_PG_HOST="sky-postgres-prod-vip-replica.<fqdn>.postgres.database.azure.com"

# Dump completo do banco no DR
pg_dump "postgresql://skyadmin:<SENHA>@${DR_PG_HOST}:5432/skydb?sslmode=require" \
  --no-owner --no-acl \
  --format=custom \
  --file=/tmp/skydb-dr-$(date +%Y%m%d%H%M%S).dump

echo "Dump concluído: $(ls -lh /tmp/skydb-dr-*.dump)"
```

### 2b. Restaurar no PostgreSQL Primary original

```bash
PRIMARY_PG_HOST="sky-postgres-prod-vip-primary.<fqdn>.postgres.database.azure.com"

# Restaurar (sobrescreve dados do primary com dados do DR)
pg_restore \
  --host="${PRIMARY_PG_HOST}" \
  --port=5432 \
  --username=skyadmin \
  --dbname=skydb \
  --no-owner --no-acl \
  --clean \
  /tmp/skydb-dr-*.dump

echo "Restauração concluída"
```

### 2c. Atualizar Key Vault Primary com secrets corretos

```bash
PRIMARY_KV_NAME=$(az keyvault list \
  --resource-group sky-aks-vip-rg \
  --query "[0].name" -o tsv)

# Restaurar database-url apontando para primary
az keyvault secret set \
  --vault-name "$PRIMARY_KV_NAME" \
  --name "database-url" \
  --value "postgresql://skyadmin:<SENHA>@${PRIMARY_PG_HOST}:5432/skydb?sslmode=require"

# Restaurar redis-url apontando para primary Redis
PRIMARY_REDIS_HOST=$(az redis show \
  --name sky-redis-prod-vip-primary \
  --resource-group sky-aks-vip-rg \
  --query "hostName" -o tsv)

PRIMARY_REDIS_KEY=$(az redis list-keys \
  --name sky-redis-prod-vip-primary \
  --resource-group sky-aks-vip-rg \
  --query "primaryKey" -o tsv)

az keyvault secret set \
  --vault-name "$PRIMARY_KV_NAME" \
  --name "redis-url" \
  --value "rediss://:${PRIMARY_REDIS_KEY}@${PRIMARY_REDIS_HOST}:6380/0"
```

---

## Fase 3 — Ativar Cluster Primary (60-90 min)

```bash
# Forçar sync do ArgoCD no cluster primary
kubectl -n argocd patch application sky-be-stg \
  --context sky-aks-vip \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}' \
  --type merge

# Verificar todos os pods saudáveis
kubectl get pods -n staging --context sky-aks-vip
```

---

## Fase 4 — Redirecionar Tráfego

O Front Door redireciona automaticamente quando o health probe detecta o primary saudável.
Verificar:

```bash
ENDPOINT=$(az afd endpoint show \
  --profile-name sky-afd-prod-vip \
  --endpoint-name sky-prod-vip \
  --resource-group sky-aks-vip-rg \
  --query "hostName" -o tsv)

# Health check
curl -sf "https://${ENDPOINT}/healthz/ready" && echo "OK" || echo "FALHOU"
```

---

## Fase 5 — Re-estabelecer Geo-replicação

Após failback completo, re-criar o link de geo-replicação do Redis:

```bash
# Recriar link Redis primary → secondary
az redis server-link create \
  --name sky-redis-prod-vip-primary \
  --resource-group sky-aks-vip-rg \
  --server-to-link sky-redis-prod-vip-secondary \
  --replication-role Secondary
```

Para o PostgreSQL, re-criar a replica via Terraform:

```bash
# Re-aplicar Terraform para recriar a replica PostgreSQL
# (a replica foi promovida durante o failover — não é mais replica)
cd infra/aks
terraform apply -var-file=environments/client-vip.tfvars -target=azurerm_postgresql_flexible_server.replica
```

---

## Checklist Final

- [ ] Região primária estável por > 2h
- [ ] Dados exportados do DR e restaurados no primary
- [ ] Key Vault primary com secrets atualizados
- [ ] Cluster primary com todos os pods Running
- [ ] Health checks passando pelo Front Door (tráfego voltou ao primary)
- [ ] Geo-replicação Redis re-estabelecida
- [ ] Replica PostgreSQL re-criada via Terraform
- [ ] Post-mortem agendado e concluído
- [ ] Documentação do incidente atualizada
