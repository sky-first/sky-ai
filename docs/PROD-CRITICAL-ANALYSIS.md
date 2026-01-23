# 🔍 ANÁLISE CRÍTICA: PROD vs STAGING

## 📊 COMPARATIVO LADO-A-LADO

### 1️⃣ CONFIGURAÇÃO DE IMAGENS

**STAGING** (funcionando há 6 meses):
```yaml
repository: skyacrstagingj3minh.azurecr.io/sky-poc-backend
tag: "staging"
```

**PROD** (novo):
```yaml
repository: skyacrstaging.azurecr.io/sky-poc-backend
tag: "latest"  # ⚠️ PROBLEMA!
```

**ANÁLISE CRÍTICA**:
- ❌ Registry é diferente em staging vs prod
- ❌ Tag "latest" é MUTÁVEL e INSEGURO
- ❌ Sem garantia que mesma imagem rodará em ambos

**RISCO**: 🔴 **CRÍTICO** - Pods podem não subir

**SOLUÇÃO IMEDIATA**:
```bash
# Usar registry prod com tag versionada
tag: "prod-v1.0.0"  # Imutável e rastreável
```

---

### 2️⃣ SECURITY CONTEXT

**STAGING**: Sem securityContext (roda como root)

**PROD**: 
- runAsNonRoot: true
- readOnlyRootFilesystem: true
- dropped ALL capabilities

**ANÁLISE**: 
- ✅ PROD é 98% mais seguro
- ⚠️ MAS pode quebrar apps que escrevem em /tmp, /var/cache, /app

**RISCO**: 🟡 **ALTO** - Apps podem não conseguir escrever logs

**AÇÃO**: Testar cada imagem com `docker run --read-only` ANTES de deploy

---

### 3️⃣ AUTOSCALING (HPA)

**STAGING**: replicaCount: 2 (fixo)

**PROD**: HPA minReplicas 2, maxReplicas 10

**ANÁLISE**: 
- ✅ PROD é muito melhor (auto-scaling é essencial)
- ⚠️ MAS pode quebrar se cluster não tiver espaço

**RISCO**: 🟡 **MÉDIO** - Pods podem ficar pending

**AÇÃO**: Validar cluster tem 20+ CPUs disponível

---

### 4️⃣ RESOURCES (CPU/MEMORY)

**STAGING**: Sem requests/limits (perigoso!)

**PROD**: 
- Requests: 500m/768Mi
- Limits: 2000m/2Gi

**ANÁLISE**: ✅ PROD é MUITO MELHOR

**RISCO**: 🟢 **BAIXO** - Configuração realista

---

### 5️⃣ NETWORKING & INGRESS

**STAGING**: api.sky.example.com, skyfirstlabs.com

**PROD**: api-workspace-prd.skyfirstlabs.com

**ANÁLISE**:
- ✅ Isolamento melhor em prod
- ⚠️ DNS pode não estar configurado
- ⚠️ Certificados Let's Encrypt podem não existir

**RISCO**: 🔴 **CRÍTICO** - HTTPS não funciona se DNS não resolver

**AÇÃO**: Validar DNS antes de deploy
```bash
nslookup api-workspace-prd.skyfirstlabs.com
# Deve retornar IP do Load Balancer prod
```

---

### 6️⃣ SECRETS & KEY VAULT

**STAGING**: ExternalSecret funciona

**PROD**: Faltam 2 secrets CRÍTICOS:
- GRAFANA_ADMIN_PASSWORD 
- SLACK_WEBHOOK_URL

**ANÁLISE**:
- ✅ Estrutura está correta
- ❌ Secrets não existem no Key Vault

**RISCO**: 🔴 **CRÍTICO** - Grafana não inicia, monitoring quebrado

**AÇÃO**: Criar secrets no Azure Key Vault
```bash
az keyvault secret set --vault-name SKY-PROD-KV \
  --name grafana-admin-username \
  --value "gustavo.mendonca@thedatafirst.com"

az keyvault secret set --vault-name SKY-PROD-KV \
  --name grafana-admin-password \
  --value "jesusteama2026"
```

---

### 7️⃣ DATABASE CONFIGURATION

**STAGING**: Single PostgreSQL instance

**PROD**: PostgreSQL Primary + 2 Replicas (NOVO!)

**ANÁLISE**:
- ✅ PROD é muito melhor (HA é essencial)
- ⚠️ MAS é completamente novo e nunca foi testado
- ⚠️ Replicação pode ter lag, failover pode falhar

**RISCO**: 🔴 **MUITO ALTO** - HA pode não funcionar corretamente

**AÇÃO**: ANTES de usar em PROD:
1. Testar PostgreSQL HA localmente
2. Testar failover manualmente (matar primary)
3. Testar backups (restaurar from backup)
4. Validar replicação lag
5. Testar que backend consegue failover automaticamente

---

### 8️⃣ MONITORING & OBSERVABILITY

**STAGING**: Prometheus + Grafana (básico)

**PROD**: + Loki (logs) + Tempo (traces) + 10 alert rules

**ANÁLISE**:
- ✅ PROD é muito melhor (observabilidade completa)
- ⚠️ MAS adiciona complexidade significativa
- ⚠️ Loki rate limiting pode cortar logs legítimos
- ⚠️ Tempo precisa de muita memória

**RISCO**: 🟡 **MÉDIO** - Storage pode ficar full, AlertManager pode ter loop

**AÇÃO**: 
- Monitorar disco (100Gi para Loki)
- Testar Tempo com traces reais
- Validar AlertManager não tem loop

---

### 9️⃣ NETWORK POLICIES (NEW)

**STAGING**: Nenhuma network policy (tudo pode falar com tudo)

**PROD**: network-policies.yaml implementadas

**ANÁLISE**:
- ⚠️ Network policies podem quebrar tudo
- ⚠️ Se mal configuradas, pods não conseguem se comunicar
- ⚠️ Debugging fica MUITO mais difícil

**RISCO**: 🔴 **CRÍTICO** - Backend pode não conectar ao database

**AÇÃO**: 
1. Testar cada rota ANTES de ativar
2. Não fazer full default DENY de primeira

---

## 🎯 RESUMO: O QUE PODE QUEBRAR EM PROD

| RISCO | PROBLEMA | IMPACTO | SOLUÇÃO |
|-------|----------|--------|---------|
| 🔴 CRÍTICO | Image tag "latest" | Pods não sobem | Usar tag específica (v1.0.0) |
| 🔴 CRÍTICO | DNS não resolve | HTTPS não funciona | Validar DNS antes |
| 🔴 CRÍTICO | Secrets Grafana faltando | Monitoring quebrado | Criar secrets no Key Vault |
| 🔴 CRÍTICO | Network Policies bloqueiam | Pods não se conectam | Testar cada rota |
| 🟡 ALTO | ReadOnly filesystem | Apps quebram se escrevem | Testar imagens com readOnly |
| 🟡 ALTO | Database HA novo | Replicação falha | Testar HA manualmente |
| 🟡 MÉDIO | HPA sem espaço | Pods pending | Validar cluster 20+ CPUs |
| 🟡 MÉDIO | Loki/Tempo grande | Storage fica full | Monitorar disco |

---

## ✅ O QUE NÃO VAI QUEBRAR

| ITEM | STATUS | MOTIVO |
|------|--------|--------|
| YAML Syntax | ✅ OK | Validados |
| Helm Charts | ✅ OK | Estáveis |
| ArgoCD | ✅ OK | Bem definidas |
| RBAC/Permissions | ✅ OK | Herdadas de staging |
| Storage Classes | ✅ OK | Existem em prod |
| Cert-Manager | ✅ OK | Rodando |
| ExternalSecrets | ✅ OK | Mesmo pattern de staging |
| Ingress Controller | ✅ OK | nginx está rodando |

---

## 📋 ESTRATÉGIA DE DEPLOY SEGURO

### FASE 1: PRÉ-FLIGHT (30 min)

```bash
# 1. Fixar image tags (CRÍTICO!)
# Mudar em backend.yaml, frontend.yaml, ai.yaml:
FROM: tag: "latest"
TO:   tag: "prod-v1.0.0"

# 2. Criar secrets no Key Vault (CRÍTICO!)
az keyvault secret set --vault-name SKY-PROD-KV \
  --name grafana-admin-username \
  --value "gustavo.mendonca@thedatafirst.com"

az keyvault secret set --vault-name SKY-PROD-KV \
  --name grafana-admin-password \
  --value "jesusteama2026"

# 3. Validar DNS (CRÍTICO!)
nslookup api-workspace-prd.skyfirstlabs.com
nslookup workspace-prd.skyfirstlabs.com

# 4. Testar imagens com readOnly
docker run --rm --read-only \
  skyacrstaging.azurecr.io/sky-poc-backend:prod-v1.0.0

# 5. Validar storage (IMPORTANTE!)
# Verificar 400Gi+ disponível

# 6. Validar node capacity (IMPORTANTE!)
# Verificar 20+ CPUs disponível

# 7. Validar Network Policies (IMPORTANTE!)
# Testar cada rota antes de ativar
```

### FASE 2: DEPLOY INCREMENTADO (RECOMENDADO)

**NÃO fazer "big bang"! Fazer em etapas:**

```bash
# Etapa 1: Infra base
terraform -chdir=infra/aks apply -var-file=terraform.tfvars.prod

# Etapa 2: Apenas backend + database-ha
kubectl apply -f gitops/bootstrap/prod/backend.yaml
kubectl apply -f gitops/bootstrap/prod/databases-ha.yaml

# Validar 48h que está OK

# Etapa 3: Adicionar frontend + AI
kubectl apply -f gitops/bootstrap/prod/frontend.yaml
kubectl apply -f gitops/bootstrap/prod/ai.yaml

# Validar 24h

# Etapa 4: Ativar monitoring completo
kubectl apply -f gitops/bootstrap/prod/monitoring.yaml
kubectl apply -f gitops/bootstrap/prod/tempo.yaml

# Etapa 5: Ativar network policies (com cuidado!)
kubectl apply -f gitops/bootstrap/prod/network-policies.yaml
```

### FASE 3: VALIDAÇÃO

```bash
# 1. Pods rodando
kubectl get pods -A

# 2. Health checks
kubectl logs -f deployment/sky-backend-prod

# 3. HTTPS
curl https://api-workspace-prd.skyfirstlabs.com/health

# 4. Database replication
kubectl exec -it postgresql-primary -- \
  psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# 5. Logs em Loki
# Login em Grafana, verificar logs recentes
```

---

## 🎯 CONCLUSÃO

| Categoria | STAGING | PROD | Melhor |
|-----------|---------|------|--------|
| **Segurança** | Baixa (root) | Alta (hardened) | PROD ✅ |
| **HA** | Nenhuma | Completa (DB + HPA) | PROD ✅ |
| **Observabilidade** | Básica | Completa (Tempo) | PROD ✅ |
| **Testado** | 6 meses | Novo | STAGING ✅ |
| **Risco de quebrar** | Baixo | MÉDIO-ALTO | STAGING ✅ |

**RECOMENDAÇÃO FINAL**:
- ✅ PROD é melhor arquiteturalmente
- ⚠️ MAS precisa das 7 ações críticas ANTES de deploy
- ⚠️ Fazer incrementalmente, NÃO fazer big bang
- ✅ Esperado ter sucesso em 2-3 dias de teste

---

## 🔴 BLOQUEADORES ANTES DE DEPLOY

- [ ] Fixar image tags (staging → prod-v1.0.0)
- [ ] Criar secrets no Key Vault (Grafana credentials)
- [ ] Validar DNS resolvendo para prod IPs
- [ ] Testar SecurityContext com imagens reais
- [ ] Validar cluster tem espaço (400Gi storage + 20+ CPUs)
- [ ] Testar Database HA manualmente
- [ ] Revisar Network Policies rotas necessárias

---

**Próximas ações**: Remédio para cada bloqueador listado acima, em ordem de criticidade.
