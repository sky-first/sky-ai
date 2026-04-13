# Sky DR Failover Runbook
**Ticket:** DO2025-1044  
**Severity:** SEV-1  
**RTO target:** 15-20 minutos  
**RPO target:** < 30s PostgreSQL / < 60s Redis

---

## Pre-requisites

- Azure CLI instalado e autenticado (`az login`)
- `kubectl` com acesso a ambos os clusters (primary e DR)
- Acesso ao portal Azure Monitor / alertas
- Grupo de contato: `#sky-oncall` no Slack

---

## Decision Gate — Declarar Desastre?

Só iniciar failover se **pelo menos 2** das condições abaixo forem verdadeiras:

| # | Condição | Verificar |
|---|----------|-----------|
| 1 | Região eastus2 com degradação confirmada pelo Azure Status | status.azure.com |
| 2 | Health probe do Front Door reporta primary DEGRADED por > 3 min | Azure Portal → Front Door → Health Probe |
| 3 | AKS primary cluster inacessível (kubectl timeout) | `kubectl get nodes --context <primary>` |
| 4 | PostgreSQL primary unreachable por > 5 min | `pg_isready -h <fqdn> -p 5432` |

> **Não fazer failover por latência isolada** — verificar se é problema de rede do cliente ou da região.

---

## Fase 1 — Diagnóstico (0-5 min)

```bash
# 1. Verificar status da Azure
curl -s "https://status.azure.com/en-us/status" | head -20

# 2. Verificar cluster primary
kubectl get nodes --context sky-aks-vip --timeout=30s

# 3. Verificar PostgreSQL primary
az postgres flexible-server show \
  --name sky-postgres-prod-vip-primary \
  --resource-group sky-aks-vip-rg \
  --query "state" -o tsv

# 4. Verificar Redis primary
az redis show \
  --name sky-redis-prod-vip-primary \
  --resource-group sky-aks-vip-rg \
  --query "provisioningState" -o tsv
```

---

## Fase 2 — Executar Failover (5-15 min)

### Opção A: Runbook Automático (recomendado)

```bash
# Executar via Azure Automation (já provisionado pelo Terraform)
az automation runbook start \
  --automation-account-name sky-automation-dr-prod-vip \
  --resource-group sky-aks-vip-rg \
  --name Sky-DR-Failover

# Acompanhar execução
az automation job list \
  --automation-account-name sky-automation-dr-prod-vip \
  --resource-group sky-aks-vip-rg \
  --query "[0].[status,startTime]" -o tsv
```

### Opção B: Manual (se Automation Account indisponível)

#### 2a. Promover PostgreSQL Replica

```bash
# Promover replica para primary independente
# AVISO: processo irreversível — a replica deixa de receber replicação
az postgres flexible-server promote \
  --name sky-postgres-prod-vip-replica \
  --resource-group sky-aks-vip-dr-rg \
  --promote-mode planned \
  --promote-option planned

# Aguardar conclusão (~5 min)
az postgres flexible-server show \
  --name sky-postgres-prod-vip-replica \
  --resource-group sky-aks-vip-dr-rg \
  --query "state" -o tsv
# Esperado: "Ready"

# Obter novo FQDN (para atualizar o Key Vault secundário)
NEW_PG_FQDN=$(az postgres flexible-server show \
  --name sky-postgres-prod-vip-replica \
  --resource-group sky-aks-vip-dr-rg \
  --query "fullyQualifiedDomainName" -o tsv)
echo "Novo PostgreSQL FQDN: $NEW_PG_FQDN"
```

#### 2b. Deslinkar Redis Secondary (habilitar escrita)

```bash
# Remover link de geo-replicação — secondary torna-se independente
az redis server-link delete \
  --name sky-redis-prod-vip-secondary \
  --resource-group sky-aks-vip-dr-rg \
  --linked-server-name sky-redis-prod-vip-primary

# Verificar status (deve ser "Succeeded")
az redis show \
  --name sky-redis-prod-vip-secondary \
  --resource-group sky-aks-vip-dr-rg \
  --query "provisioningState" -o tsv
```

#### 2c. Atualizar secrets no Key Vault secundário

```bash
DR_KV_NAME=$(az keyvault list \
  --resource-group sky-aks-vip-dr-rg \
  --query "[0].name" -o tsv)

# Atualizar database-url com FQDN da replica promovida
az keyvault secret set \
  --vault-name "$DR_KV_NAME" \
  --name "database-url" \
  --value "postgresql://skyadmin:<SENHA>@${NEW_PG_FQDN}:5432/skydb?sslmode=require"

# Atualizar redis-url com o secondary (agora primary)
DR_REDIS_HOST=$(az redis show \
  --name sky-redis-prod-vip-secondary \
  --resource-group sky-aks-vip-dr-rg \
  --query "hostName" -o tsv)

DR_REDIS_KEY=$(az redis list-keys \
  --name sky-redis-prod-vip-secondary \
  --resource-group sky-aks-vip-dr-rg \
  --query "primaryKey" -o tsv)

az keyvault secret set \
  --vault-name "$DR_KV_NAME" \
  --name "redis-url" \
  --value "rediss://:${DR_REDIS_KEY}@${DR_REDIS_HOST}:6380/0"
```

---

## Fase 3 — Ativar Secondary Cluster (10-20 min)

```bash
# Obter credenciais do cluster DR
az aks get-credentials \
  --name sky-aks-vip-dr \
  --resource-group sky-aks-vip-dr-rg \
  --context sky-aks-vip-dr

# Verificar nós do cluster DR
kubectl get nodes --context sky-aks-vip-dr

# Forçar sync do ArgoCD no cluster DR (garantir que apps estão rodando)
kubectl -n argocd patch application sky-be-stg \
  --context sky-aks-vip-dr \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}' \
  --type merge

# Verificar pods em execução
kubectl get pods -n staging --context sky-aks-vip-dr
```

---

## Fase 4 — Validação (após ativação)

```bash
# Smoke tests básicos
ENDPOINT=$(az afd endpoint show \
  --profile-name sky-afd-prod-vip \
  --endpoint-name sky-prod-vip \
  --resource-group sky-aks-vip-rg \
  --query "hostName" -o tsv)

# Health check
curl -sf "https://${ENDPOINT}/healthz/ready" && echo "OK" || echo "FALHOU"

# Teste de autenticação (retorno 401 = backend ativo)
curl -s -o /dev/null -w "%{http_code}" "https://${ENDPOINT}/api/auth/login"
```

---

## Fase 5 — Comunicação

1. Notificar cliente via canal dedicado
2. Abrir ticket de incidente com timestamp de início
3. Atualizar status page (se disponível)
4. Agendar chamada de post-mortem em 48h

---

## Checklist Final

- [ ] PostgreSQL replica promovida com sucesso
- [ ] Redis secondary aceitando escritas
- [ ] Key Vault DR com secrets atualizados
- [ ] Cluster DR com todos os pods Running
- [ ] Health checks passando pelo Front Door
- [ ] Cliente notificado
- [ ] Ticket de incidente aberto

---

## Próximo Passo

Após estabilização, planejar failback: [dr-failback.md](./dr-failback.md)
