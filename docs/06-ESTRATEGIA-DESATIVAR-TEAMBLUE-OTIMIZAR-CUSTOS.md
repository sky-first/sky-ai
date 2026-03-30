# 💰 Estratégia: Desativar TeamBlue e Otimizar Custos - Melhores Práticas

**Data**: 30 de Março de 2026  
**Status**: 📋 **PLANEJAMENTO APENAS** (NÃO EXECUTAR AINDA)  
**Objetivo**: Deixar apenas staging ativo + reduzir custos 40-60%

---

## 🎯 Situação Atual vs Objetivo

### Antes (Estado Atual)
```
Ambientes Ativos:
  ✅ staging: AKS + TeamBlue namespace + recursos
  ❌ produção: Não existe
  ❌ teamblue: Precisa desativar
  
Custo Mensal Estimado:
  - AKS cluster: ~$300-400
  - Node pools: ~$400-600
  - Storage/Database: ~$200-300
  - TOTAL: ~$900-1300/mês
```

### Depois (Objetivo)
```
Ambientes Ativos:
  ✅ staging: AKS + apenas aplicações essenciais
  ❌ produção: Não existe (futuro)
  ❌ teamblue: DESATIVADO
  
Custo Mensal Estimado:
  - AKS cluster: ~$300-400 (não muda)
  - Node pools: ~$100-150 (reduzido 70%)
  - Storage/Database: ~$50-100 (reduzido 70%)
  - TOTAL: ~$450-650/mês (redução 50%)
```

---

## 📊 Análise: O Que É TeamBlue?

### Componentes TeamBlue em Staging

```
Kubernetes Namespace: teamblue
  ├─ Pods:
  │  ├─ sky-be-teamblue-stg (Backend API)
  │  ├─ sky-fe-teamblue-stg (Frontend)
  │  ├─ sky-teamblue-ai-worker (AI Worker)
  │  ├─ postgres.teamblue (Database)
  │  └─ redis.teamblue (Cache)
  │
  ├─ ConfigMaps:
  │  ├─ values-sky-be-teamblue-stg.yaml
  │  ├─ values-sky-fe-teamblue-stg.yaml
  │  └─ values-teamblue-ai-worker-stg.yaml
  │
  ├─ Secrets:
  │  ├─ database-secrets-teamblue.yaml
  │  └─ regcred (Image Pull Secrets)
  │
  ├─ Services:
  │  ├─ teamblue-api.skyfirstlabs.com (Ingress)
  │  ├─ plataform.teamblue-stg.skyfirstlabs.com (Frontend)
  │  └─ Internal DNS: postgres.teamblue.svc.cluster.local
  │
  └─ Infrastructure:
     ├─ Compute: pods (CPU/Memory allocations)
     ├─ Storage: PVCs para PostgreSQL
     └─ Network: Ingress rules + TLS certs
```

### Custo Quebrado - TeamBlue

```
Node Pools:
  - userapps: 1-3 nodes @ $100-150/mês/node = $100-450/mês
  - aicpu16: 0-1 nodes @ $200-300/mês = $0-300/mês
  → TeamBlue usa: ~$150-300/mês (30-40% do custo)

Storage:
  - PostgreSQL PVC: ~$50-100/mês (database storage)
  - Redis: ~$20/mês (cache)
  → TeamBlue storage: ~$70-120/mês

Networking:
  - Public IP (Ingress): ~$2-5/mês
  → TeamBlue networking: ~$5-10/mês

TOTAL TeamBlue: ~$225-430/mês (25-40% do orçamento)
```

---

## 🔧 Opções de Desativação (Do Menos ao Mais Agressivo)

### Opção 1: SCALE DOWN (Mínimo Risco)
**O que faz**: Reduz pods a 0, mantém configuração

```
Impacto: ⚠️ Médio
  ✅ TeamBlue offline
  ✅ Configuração preservada (pode reativar em 5 min)
  ✅ Custo reduz 70-80%
  ❌ Recurso Kubernetes ainda existe (ocupa 2-5% custo)

Como fazer:
  1. Scale down deployment → replicas: 0
  2. Scale down StatefulSet (PostgreSQL) → replicas: 0
  3. Manter secrets, ConfigMaps, PVCs (não deletar)

Arquivo: gitops/bootstrap/staging/
  - Manter: database-secrets-teamblue.yaml
  - Modificar: Helm values → replicas: 0

Tempo: 2-3 minutos
Reversível: ✅ SIM (5 minutos)
Risco de Dados: ❌ NÃO (PVC persiste)
```

### Opção 2: SUSPEND (Médio Risco)
**O que faz**: Pausar aplicação + manter dados, remover recursos não-essenciais

```
Impacto: ⚠️ Alto
  ✅ TeamBlue offline
  ✅ Dados preservados (PostgreSQL volumes)
  ✅ Custo reduz 85-90%
  ⚠️ Recriação precisa 15-20 min

Como fazer:
  1. Delete: Deployments (frontend, backend, workers)
  2. Delete: Services, Ingress rules
  3. Delete: PVCs (CUIDADO: perdem dados!)
  4. Keep: Secrets, ConfigMaps (para recriação)
  5. Keep: Namespace (baixo custo)

Arquivo: gitops/bootstrap/staging/
  - Delete: values-sky-*-teamblue-stg.yaml
  - Keep: database-secrets-teamblue.yaml (backup)
  - Keep: regcred-es.yaml (namespace teamblue)

Tempo: 5-10 minutos
Reversível: ⚠️ PARCIAL (requer backup PVC ou new database)
Risco de Dados: ⚠️ ALTO (sem backup de PVC)
```

### Opção 3: FULL REMOVAL (Máximo Risco)
**O que faz**: Remover tudo (só para se não vai usar nunca mais)

```
Impacto: 🔴 Crítico
  ✅ TeamBlue 100% offline
  ✅ Custo reduz 100% (para TeamBlue)
  ❌ Recriação precisa rebuild completo
  ❌ Dados perdidos (sem backup externo)

Como fazer:
  1. Delete: Namespace teamblue (deleta tudo dentro)
  2. Delete: Secret regcred no namespace teamblue
  3. Delete: Todas config files

Arquivo: gitops/bootstrap/staging/
  - Delete: database-secrets-teamblue.yaml
  - Delete: values-sky-*-teamblue-stg.yaml
  - Delete: Ingress rules para teamblue.skyfirstlabs.com

Tempo: 2-3 minutos
Reversível: ❌ NÃO (requer restore ou rebuild)
Risco de Dados: 🔴 CRÍTICO (tudo deletado)
```

---

## ✅ RECOMENDAÇÃO: Opção 1 (SCALE DOWN)

### Por Quê?

```
Razões para Opção 1:
  1. Máxima segurança (dados preservados)
  2. Máxima reversibilidade (5 min para reativar)
  3. Custo otimizado (70-80% redução TeamBlue)
  4. Manutenção fácil (só mudar replicas: 0)
  5. Sem perda de conhecimento (config mantido)
  6. Compatível com "futuro reavaliar" mentalidade
```

### Arquivos a Modificar (Scale Down)

```
1. gitops/bootstrap/staging/ingress-nginx.yaml
   → Sem mudança (WAF continua ativo, protege staging)

2. gitops/charts/common-app/values-sky-be-teamblue-stg.yaml
   → Mudar: replicaCount: 0 (era 1-2)

3. gitops/charts/common-app/values-sky-fe-teamblue-stg.yaml
   → Mudar: replicaCount: 0 (era 1)

4. gitops/charts/common-app/values-teamblue-ai-worker-stg.yaml
   → Mudar: replicaCount: 0 (era 1)

5. gitops/bootstrap/staging/database-secrets-teamblue.yaml
   → MANTER (backup para futuro reativação)

Deletar:
   ❌ Nada! (only scale down replicas to 0)
```

### Git Changes Summary (Scale Down)

```bash
# Files to modify:
  ✏️ gitops/charts/common-app/values-sky-be-teamblue-stg.yaml
  ✏️ gitops/charts/common-app/values-sky-fe-teamblue-stg.yaml
  ✏️ gitops/charts/common-app/values-teamblue-ai-worker-stg.yaml

# Files to keep:
  ✅ gitops/bootstrap/staging/database-secrets-teamblue.yaml
  ✅ gitops/manifests/security/staging/regcred-es.yaml

# Change pattern: replicaCount: X → replicaCount: 0
```

---

## 🚀 Como Executar (Step-by-Step - AINDA NÃO FAZER)

### Fase 1: Backup (Segurança)

```bash
# 1. Extrair current config de teamblue (para backup)
kubectl get ns teamblue -o yaml > /backup/teamblue-ns-backup.yaml
kubectl get secrets -n teamblue -o yaml > /backup/teamblue-secrets-backup.yaml
kubectl get configmaps -n teamblue -o yaml > /backup/teamblue-configmaps-backup.yaml
kubectl describe pvc -n teamblue > /backup/teamblue-pvc-describe.txt

# 2. Backup database (se precisa dados históricos)
kubectl exec -n teamblue postgres-0 -- pg_dump ai_saas_db > /backup/teamblue-db-backup.sql

Status: ✅ Dados seguros offline
```

### Fase 2: Scale Down (ArgoCD)

```bash
# 1. Modify Helm values → replicaCount: 0
cd gitops/charts/common-app/
  sed -i 's/replicaCount: [0-9]\+/replicaCount: 0/' values-sky-be-teamblue-stg.yaml
  sed -i 's/replicaCount: [0-9]\+/replicaCount: 0/' values-sky-fe-teamblue-stg.yaml
  sed -i 's/replicaCount: [0-9]\+/replicaCount: 0/' values-teamblue-ai-worker-stg.yaml

# 2. Commit changes
git add gitops/charts/common-app/values-sky-*-teamblue-stg.yaml
git commit -m "chore: scale down teamblue replicas to 0 for cost optimization"
git push origin staging

# 3. ArgoCD sync (automatic or manual)
# Watch ArgoCD UI or run:
argocd app sync sky-be-teamblue-stg

Status: ✅ Pods removed, PVCs preserved
Time: ~2-3 minutes
```

### Fase 3: Validação

```bash
# 1. Verify scale down
kubectl get pods -n teamblue
# Expected: No pods running

# 2. Verify data preserved
kubectl get pvc -n teamblue
# Expected: PVCs in status "Bound" (data intact)

# 3. Monitor cost (24h later)
# Azure Portal → Resource Group → Costs
# Expected: Cost reduced 20-30%

Status: ✅ TeamBlue offline, dados seguros
```

---

## 💾 Reativação Rápida (Se Precisa Depois)

### Se Precisa Ligar TeamBlue Novamente

```bash
# 1. Restore replica count
cd gitops/charts/common-app/
  sed -i 's/replicaCount: 0/replicaCount: 1/' values-sky-be-teamblue-stg.yaml
  sed -i 's/replicaCount: 0/replicaCount: 1/' values-sky-fe-teamblue-stg.yaml
  sed -i 's/replicaCount: 0/replicaCount: 1/' values-teamblue-ai-worker-stg.yaml

# 2. Commit e push
git add gitops/charts/common-app/values-sky-*-teamblue-stg.yaml
git commit -m "chore: reactivate teamblue - scale up replicas"
git push origin staging

# 3. ArgoCD sync
argocd app sync sky-be-teamblue-stg

Time: ~5-10 minutes (pods restart, cache warm up)
Data: ✅ 100% preserved (no loss)
```

---

## 📈 Impacto na Infraestrutura Geral

### Node Scaling Automático

```
ANTES (com TeamBlue):
  - Node Pool "userapps": 1-3 nodes
  - Node Pool "aicpu16": 0-1 nodes
  - Total: 1-4 nodes active

DEPOIS (sem TeamBlue):
  - Node Pool "userapps": 1-2 nodes (auto-scale reduce)
  - Node Pool "aicpu16": 0 nodes (idle)
  - Total: 1-2 nodes active

Kubernetes auto-scaler (já ativo em terraform):
  ✅ Detecta menos demanda
  ✅ Scale down nodes automaticamente
  ✅ Reduz custo compute 60-70%
```

### StorageClass (PVC Behavior)

```
ANTES (com TeamBlue PVCs):
  - PostgreSQL PVC: 10GB @ $2/GB/mês = $20/mês
  - Redis Cache: 2GB @ $2/GB/mês = $4/mês

DEPOIS (scale down):
  - PostgreSQL PVC: Still 10GB (occupied but unused)
  - Redis Cache: Still 2GB (occupied but unused)
  - Cost: Mantém mesmo (storage não deletado)

⚠️ Se quer reduzir storage cost 100%:
   - Opção: Delete PVCs (Opção 2/3)
   - Risco: Perde dados
   - Alternativa: Backup to Azure Blob Storage ($0.01/GB/mês)
```

---

## 🛡️ Melhores Práticas Implementadas

### 1️⃣ Infrastructure as Code (IaC) Approach
```
✅ Mudanças via Helm/GitOps (não manual)
✅ All changes tracked em git
✅ Reversível via git revert
✅ Auditável (commit history)
```

### 2️⃣ Data Protection
```
✅ Backup antes de qualquer mudança
✅ PVCs preservados (não deletar)
✅ Secrets mantidos (rápida reativação)
✅ Database backup offsite possível
```

### 3️⃣ Cost Optimization
```
✅ Scale to zero (não delete)
✅ Deixar infrastructure intact
✅ Só remover recursos computacionais
✅ Rápida reversão sem recriação
```

### 4️⃣ Operational Continuity
```
✅ Zero downtime staging (WAF continua)
✅ Logging/monitoring não afetado
✅ Certificate renewal não afetado
✅ DNS records não afetado
```

### 5️⃣ Team Communication
```
✅ Documentação clara (este arquivo)
✅ Passo-a-passo descrito
✅ Riscos explicitados
✅ Rollback procedures documentados
```

---

## 📋 Decision Matrix

| Aspecto | Opção 1 (Scale Down) | Opção 2 (Suspend) | Opção 3 (Remove) |
|--------|----------------------|-------------------|------------------|
| **Custo Redução** | 70-80% | 85-90% | 100% |
| **Reversibilidade** | ✅ 5 min | ⚠️ 15-20 min | ❌ Rebuild |
| **Data Loss Risk** | ❌ 0% | ⚠️ Alto | 🔴 Total |
| **Operacional Complexidade** | ✅ Simples | ⚠️ Médio | 🔴 Alto |
| **Recomendação** | ✅ **USAR ISTO** | ⚠️ Se tem backup | ❌ Nunca |

---

## ✅ Próximas Ações (Para User Confirmar)

### Opção A: Implementar Agora
```
1. Confirmar: "OK, vamos escalar down teamblue"
2. Agent: Modifica 3 arquivos + git push
3. Tempo: 5-10 minutos
4. Resultado: 70% redução custo TeamBlue
```

### Opção B: Estudar Mais
```
1. User: "Preciso revisar algo"
2. Agent: Esclarece dúvida específica
3. Depois volta a decidir
```

### Opção C: Agendar Para Depois
```
1. User: "Deixa para outro dia"
2. Agent: Mantém doc disponível
3. Reutiliza quando pronto
```

---

**Status**: 📋 PLANEJAMENTO (aguardando decisão)  
**Risco**: 🟢 BAIXO (máximo 5% custo TeamBlue preservado)  
**Reversibilidade**: ✅ 100% (5 minutos)  
**Recomendação**: ✅ **Implementar Opção 1 agora**
