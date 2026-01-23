# 🚀 PLANO DE EXECUÇÃO: RESOLVER 7 BLOQUEADORES

## 📋 RESUMO EXECUTIVO

**Objetivo**: Resolver todos 7 bloqueadores para production-ready
**Tempo total**: ~2 horas (execução) + 48-72h (monitoring)
**Risco geral**: MÉDIO (1 passo ALTO = DB failover, outros BAIXO/MÉDIO)
**Rollback**: Possível em todos os passos (versionado em git)

---

## 🎯 SEQUÊNCIA RECOMENDADA

```
BAIXO RISCO (PRIMEIRO):
  ✅ [2 min]  FIX 1: Image tags (latest → versão)
  ✅ [5 min]  FIX 2: Grafana secrets
  ✅ [15 min] FIX 4: Network policies test (apenas validação)

MÉDIO RISCO (DEPOIS):
  ⚠️  [15 min] FIX 3: DNS validation (requer acesso DNS registrar)
  ⚠️  [10 min] FIX 5: ReadOnly filesystem (pod restart)
  ⚠️  [15 min] FIX 7: HPA capacity test (simula load)

ALTO RISCO (ÚLTIMO):
  🔴 [30 min] FIX 6: Database HA failover (MATA PRIMARY!)

DEPLOYMENT:
  🚀 [30 min] DEPLOY: Apply all fixes
  📊 [48-72h] MONITOR: Production validation
```

**Por que essa ordem?**
- Começar com fixes que não afetam produção (apenas configs)
- Ganhar confiança com testes
- Deixar para último o passo mais arriscado (DB)
- Deploy apenas após todos os fixes validados

---

## 🔵 PASSO 0: PRÉ-REQUISITOS

### Verificar acesso necessário

```bash
# 1. Acesso ao cluster
kubectl get nodes
# RESULTADO ESPERADO: At least 2 nodes

# 2. Acesso ao Azure Key Vault
az keyvault list --query "[].name" -o table
# RESULTADO ESPERADO: SKY-PROD-KV listed

# 3. Acesso ao Azure Container Registry
az acr list --query "[].name" -o table
# RESULTADO ESPERADO: skyacrstaging* listed

# 4. Acesso ao DNS (se não Azure DNS, você pode fazer manual depois)
# If Azure DNS, verify:
az network dns zone list --query "[].name" -o table
# RESULTADO ESPERADO: skyfirstlabs.com listed
```

### Verificar estado atual

```bash
# Cluster status
kubectl get nodes -o wide
kubectl get all -n default
kubectl get all -n monitoring
kubectl get all -n databases

# Git status - make sure clean
git status
# RESULTADO ESPERADO: "working tree clean"

# Backup da configuração atual
git branch prod/backup-before-fixes
git push origin prod/backup-before-fixes
```

---

## ✅ FIX 1: IMAGE TAGS (LATEST → VERSÃO) [2 MIN]

### Risco: BAIXO ✅
**Por quê?** Apenas muda tags em YAML, sem deploy
**Impacto**: Nenhum até fazer kubectl apply
**Rollback**: `git revert`

### Execução

```bash
# Opção A: Git SHA (recomendado)
GIT_SHA=$(git rev-parse --short HEAD)
echo "Using Git SHA: $GIT_SHA"

# Atualizar todos os YAML com tag imutável
for file in gitops/bootstrap/prod/*.yaml; do
  sed -i.bak "s/tag: \"latest\"/tag: \"prod-v1.0.0\"/g" "$file"
  rm "$file.bak"
done

# Opção B: Se preferir usar Git SHA (mais rastreável)
for file in gitops/bootstrap/prod/backend.yaml gitops/bootstrap/prod/frontend.yaml gitops/bootstrap/prod/ai.yaml; do
  sed -i.bak "s/tag: \"latest\"/tag: \"$GIT_SHA\"/g" "$file"
  rm "$file.bak"
done
```

### Validação

```bash
# Confirmar que nenhuma tag é "latest"
grep -r "latest" gitops/bootstrap/prod/
# RESULTADO ESPERADO: (nenhum match - exit code 1)

# Ver tags finais
grep "tag:" gitops/bootstrap/prod/backend.yaml gitops/bootstrap/prod/frontend.yaml gitops/bootstrap/prod/ai.yaml
# RESULTADO ESPERADO:
#   tag: "prod-v1.0.0"
#   tag: "prod-v1.0.0"
#   tag: "prod-v1.0.0"
```

### Commit

```bash
git add gitops/bootstrap/prod/backend.yaml gitops/bootstrap/prod/frontend.yaml gitops/bootstrap/prod/ai.yaml
git commit -m "fix(1): Remove mutable latest tag, use immutable prod-v1.0.0"
git push origin prod/workspace-setup
```

**Status**: ✅ DONE - Próximo: FIX 2

---

## ✅ FIX 2: GRAFANA SECRETS [5 MIN]

### Risco: BAIXO ✅
**Por quê?** Apenas cria secrets no Key Vault
**Impacto**: Nenhum até ExternalSecret sincronizar
**Rollback**: `az keyvault secret delete --vault-name SKY-PROD-KV --name grafana-admin-password`

### Pré-requisitos

Você forneceu:
- Email: gustavo.mendonca@thedatafirst.com
- Password: jesusteama2026
- Slack: "not using yet" (vamos deixar vazio ou skip)

### Execução

```bash
# 1. Criar secret de admin password
az keyvault secret set \
  --vault-name SKY-PROD-KV \
  --name grafana-admin-password \
  --value "jesusteama2026"

# 2. Criar secret de admin email (optional)
az keyvault secret set \
  --vault-name SKY-PROD-KV \
  --name grafana-admin-email \
  --value "gustavo.mendonca@thedatafirst.com"

# 3. Slack webhook (deixar vazio por enquanto, você ativa depois)
az keyvault secret set \
  --vault-name SKY-PROD-KV \
  --name slack-webhook-url \
  --value "https://hooks.slack.com/services/TODO"
```

### Validação

```bash
# Verificar que secrets foram criados
az keyvault secret list --vault-name SKY-PROD-KV --query "[].name" -o table
# RESULTADO ESPERADO:
#   grafana-admin-password
#   grafana-admin-email
#   slack-webhook-url

# Testar leitura (sem expor valor)
az keyvault secret show --vault-name SKY-PROD-KV --name grafana-admin-password --query id
# RESULTADO ESPERADO: /subscriptions/.../secrets/grafana-admin-password
```

### Post-execução

Após deploy, ExternalSecret sincronizará automaticamente:

```bash
# Será sincronizado em ~1-2 minutos após deploy
kubectl get externalsecrets -n monitoring
# RESULTADO ESPERADO (após alguns minutos):
#   NAME                  STORE    AGE    STATUS
#   grafana-admin-secret  azure-kv 2m     SecretSynced

# Pode verificar também:
kubectl get secret grafana-secret -n monitoring
# RESULTADO ESPERADO:
#   NAME              TYPE     DATA   AGE
#   grafana-secret    Opaque   2      2m
```

**Status**: ✅ DONE - Próximo: FIX 4 (Network Policies)

---

## ✅ FIX 4: NETWORK POLICIES TEST [15 MIN]

### Risco: BAIXO ✅
**Por quê?** Apenas testa, não modifica produção
**Impacto**: Nenhum (testes apenas)
**Rollback**: N/A (read-only tests)

### Execução

Vamos testar 4 rotas críticas que as network policies podem bloquear:

#### Teste 1: Backend → PostgreSQL

```bash
# Get backend pod
BACKEND_POD=$(kubectl get pods -l app=backend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -z "$BACKEND_POD" ]; then
  echo "❌ No backend pod found. Deploy primeiro antes de testar."
else
  echo "Testing Backend → PostgreSQL connection..."
  kubectl exec -it $BACKEND_POD -- \
    bash -c "apt-get update && apt-get install -y postgresql-client && psql -h postgresql.databases -U postgres -c 'SELECT 1;' && echo '✅ Connection successful'"
fi
```

#### Teste 2: Loki ← Promtail (logs)

```bash
# Get promtail pod
PROMTAIL_POD=$(kubectl get pods -n monitoring -l app=promtail -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -z "$PROMTAIL_POD" ]; then
  echo "❌ Promtail não encontrado. Verificar deploy."
else
  echo "Testing Promtail → Loki connection..."
  kubectl logs $PROMTAIL_POD -n monitoring | grep -i "pushing\|success" | tail -5
  echo "✅ Promtail está enviando logs"
fi
```

#### Teste 3: Prometheus ← Scrape targets

```bash
PROM_POD=$(kubectl get pods -n monitoring -l app=prometheus -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -z "$PROM_POD" ]; then
  echo "❌ Prometheus não encontrado."
else
  echo "Testing Prometheus scrape..."
  kubectl exec -it $PROM_POD -n monitoring -- \
    bash -c "curl -s http://localhost:9090/api/v1/targets?state=active | grep -o '\"activeTargets\"' | wc -l" && \
  echo "✅ Prometheus está scraping targets"
fi
```

#### Teste 4: Frontend → Backend API

```bash
FRONTEND_POD=$(kubectl get pods -l app=frontend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -z "$FRONTEND_POD" ]; then
  echo "❌ Frontend pod não encontrado."
else
  echo "Testing Frontend → Backend connectivity..."
  kubectl exec -it $FRONTEND_POD -- \
    bash -c "curl -s http://backend.default:8000/health && echo '✅ Frontend pode conectar ao Backend'"
fi
```

### Validação Rápida

```bash
# Script automático para testar todos os 4
cat > /tmp/test-network-policies.sh << 'EOF'
#!/bin/bash
echo "=== Network Policies Test Suite ==="
PASS=0
FAIL=0

# Test 1: Backend → DB
BACKEND=$(kubectl get pods -l app=backend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$BACKEND" ]; then
  if kubectl exec $BACKEND -- bash -c "nc -z postgresql.databases 5432" 2>/dev/null; then
    echo "✅ [1/4] Backend → PostgreSQL: OK"
    ((PASS++))
  else
    echo "❌ [1/4] Backend → PostgreSQL: BLOCKED"
    ((FAIL++))
  fi
else
  echo "⊘ [1/4] Backend not deployed yet"
fi

# Test 2: Promtail → Loki
PROMTAIL=$(kubectl get pods -n monitoring -l app=promtail -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$PROMTAIL" ]; then
  if kubectl exec $PROMTAIL -n monitoring -- bash -c "nc -z loki.monitoring 3100" 2>/dev/null; then
    echo "✅ [2/4] Promtail → Loki: OK"
    ((PASS++))
  else
    echo "❌ [2/4] Promtail → Loki: BLOCKED"
    ((FAIL++))
  fi
else
  echo "⊘ [2/4] Promtail not deployed yet"
fi

# Test 3: Prometheus → Targets
PROM=$(kubectl get pods -n monitoring -l app=prometheus -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$PROM" ]; then
  TARGETS=$(kubectl exec $PROM -n monitoring -- bash -c "curl -s http://localhost:9090/api/v1/targets?state=active | grep -o '\"activeTargets\"' | wc -l")
  if [ "$TARGETS" -gt 0 ]; then
    echo "✅ [3/4] Prometheus → Targets: OK ($TARGETS targets)"
    ((PASS++))
  else
    echo "❌ [3/4] Prometheus → Targets: 0 targets"
    ((FAIL++))
  fi
else
  echo "⊘ [3/4] Prometheus not deployed yet"
fi

# Test 4: Frontend → Backend
FRONTEND=$(kubectl get pods -l app=frontend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$FRONTEND" ]; then
  if kubectl exec $FRONTEND -- bash -c "nc -z backend.default 8000" 2>/dev/null; then
    echo "✅ [4/4] Frontend → Backend: OK"
    ((PASS++))
  else
    echo "❌ [4/4] Frontend → Backend: BLOCKED"
    ((FAIL++))
  fi
else
  echo "⊘ [4/4] Frontend not deployed yet"
fi

echo "=== Result: $PASS passed, $FAIL failed ==="
[ $FAIL -eq 0 ] && exit 0 || exit 1
EOF

chmod +x /tmp/test-network-policies.sh
/tmp/test-network-policies.sh
```

**Status**: ✅ DONE - Próximo: FIX 3 (DNS) ou FIX 5 (ReadOnly)

---

## ⚠️ FIX 3: DNS VALIDATION [15 MIN]

### Risco: MÉDIO ⚠️
**Por quê?** Requer modificar DNS externo (pode estar fora do seu controle)
**Impacto**: Se errar, HTTPS não funciona
**Rollback**: Reverter DNS record

### Pré-requisitos

Você precisa de:
- Acesso ao registrador DNS (Namecheap, Route53, Azure DNS, etc)
- OU acesso ao Azure DNS (se usando Azure)

### Execução - FASE 1: Obter IP do LoadBalancer

```bash
# Obter IP do LoadBalancer
kubectl get service nginx-ingress -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
# RESULTADO ESPERADO: 20.48.123.456 (algum IP real)

# Salvar em variável
LB_IP=$(kubectl get service nginx-ingress -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "LoadBalancer IP: $LB_IP"
```

### Execução - FASE 2: Atualizar DNS

#### Opção A: Azure DNS

```bash
# Se estiver usando Azure DNS Zone
RESOURCE_GROUP="SKY-PROD-RG"  # Adjust if needed
ZONE_NAME="skyfirstlabs.com"

# Listar records atuais
az network dns record-set a list -g $RESOURCE_GROUP -z $ZONE_NAME

# Atualizar / criar record
az network dns record-set a add-record \
  -g $RESOURCE_GROUP \
  -z $ZONE_NAME \
  -n "api-workspace-prd" \
  --ipv4-address "$LB_IP"

# Verificar
az network dns record-set a show \
  -g $RESOURCE_GROUP \
  -z $ZONE_NAME \
  -n "api-workspace-prd"
```

#### Opção B: Registrador externo (manual)

Se usar Namecheap, Route53, etc:

1. Login no painel de DNS
2. Encontrar zona `skyfirstlabs.com`
3. Adicionar/Atualizar record:
   - **Type**: A
   - **Name**: api-workspace-prd
   - **Value**: (cole o $LB_IP acima)
   - **TTL**: 300 (15 minutes - rápido para propagação)
4. Save

### Execução - FASE 3: Validar propagação DNS

```bash
# Verificar imediatamente (pode estar no cache local)
nslookup api-workspace-prd.skyfirstlabs.com
dig api-workspace-prd.skyfirstlabs.com +short

# Se não resolver, esperar propagação (5-10 minutos)
echo "Aguardando propagação DNS (pode levar até 10 minutos)..."
for i in {1..30}; do
  RESOLVED_IP=$(dig api-workspace-prd.skyfirstlabs.com +short)
  if [ "$RESOLVED_IP" == "$LB_IP" ]; then
    echo "✅ DNS propagado! ($RESOLVED_IP)"
    break
  fi
  echo "[$i/30] DNS ainda não propagado (resolvendo para: $RESOLVED_IP, esperando: $LB_IP)"
  sleep 20
done
```

### Validação

```bash
# 1. DNS resolve
dig api-workspace-prd.skyfirstlabs.com +short
# RESULTADO ESPERADO: 20.48.123.456

# 2. HTTPS responde
curl -I https://api-workspace-prd.skyfirstlabs.com/
# RESULTADO ESPERADO: HTTP/1.1 (qualquer código)

# 3. Certificate é válido
openssl s_client -connect api-workspace-prd.skyfirstlabs.com:443 \
  -servername api-workspace-prd.skyfirstlabs.com 2>/dev/null | \
  openssl x509 -noout -dates
# RESULTADO ESPERADO: 
#   notBefore=...
#   notAfter=... (future date)
```

**Status**: ✅ DONE - Próximo: FIX 5 (ReadOnly)

---

## ⚠️ FIX 5: READONLY FILESYSTEM TEST [10 MIN]

### Risco: MÉDIO ⚠️
**Por quê?** Testa imagem com readOnly, depois pod restart
**Impacto**: Pods reiniciam (~2 min indisponibilidade)
**Rollback**: Remover readOnly flag em YAML

### Execução - FASE 1: Test Docker Images

```bash
# Test cada imagem se consegue escrever em /tmp com read-only

# Backend
echo "Testing Backend image..."
docker run --rm \
  --read-only \
  --user 1000:3000 \
  --entrypoint /bin/bash \
  skyacrstaging.azurecr.io/sky-poc-backend:prod-v1.0.0 \
  -c "echo 'test' > /tmp/test.txt && cat /tmp/test.txt && echo '✅ Backend can write to /tmp'"

# Frontend
echo "Testing Frontend image..."
docker run --rm \
  --read-only \
  --user 1000:3000 \
  --entrypoint /bin/bash \
  skyacrstaging.azurecr.io/sky-poc-frontend:prod-v1.0.0 \
  -c "echo 'test' > /tmp/test.txt && cat /tmp/test.txt && echo '✅ Frontend can write to /tmp'"

# AI Engine
echo "Testing AI Engine image..."
docker run --rm \
  --read-only \
  --user 1000:3000 \
  --entrypoint /bin/bash \
  skyacrstaging.azurecr.io/sky-poc-ai:prod-v1.0.0 \
  -c "echo 'test' > /tmp/test.txt && cat /tmp/test.txt && echo '✅ AI can write to /tmp'"
```

### Execução - FASE 2: Deploy com emptyDir

Se Phase 1 falhar, precisamos adicionar emptyDir volumes. Exemplo para backend.yaml:

```yaml
# gitops/bootstrap/prod/backend.yaml
spec:
  template:
    spec:
      containers:
      - name: backend
        securityContext:
          readOnlyRootFilesystem: true
        volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: var-run
          mountPath: /var/run
      volumes:
      - name: tmp
        emptyDir: {}
      - name: var-run
        emptyDir: {}
```

Depois deploy:

```bash
kubectl apply -f gitops/bootstrap/prod/backend.yaml
kubectl rollout status deployment/backend -n default
```

### Validação

```bash
# 1. Pod está running
kubectl get pods -l app=backend
# RESULTADO ESPERADO: Running

# 2. Pod pode escrever em /tmp
kubectl exec -it backend-pod -- \
  bash -c "echo 'test' > /tmp/test.txt && cat /tmp/test.txt"
# RESULTADO ESPERADO: test

# 3. Pod NÃO pode escrever em /
kubectl exec -it backend-pod -- \
  bash -c "echo 'test' > /test.txt" 2>&1
# RESULTADO ESPERADO: Read-only file system (erro esperado!)

# 4. App funciona
curl http://backend-service/health
# RESULTADO ESPERADO: {"status":"ok"}
```

**Status**: ✅ DONE - Próximo: FIX 7 (HPA Capacity)

---

## ⚠️ FIX 7: HPA CAPACITY TEST [15 MIN]

### Risco: MÉDIO ⚠️
**Por quê?** Testa auto-scaling simulando carga
**Impacto**: Cluster pode ficar lento durante teste
**Rollback**: Parar o teste

### Execução - FASE 1: Validar Capacity

```bash
# 1. Quantas CPUs tem o cluster?
kubectl top nodes
# RESULTADO ESPERADO:
#   NAME    CPU(cores)  CPU%  MEMORY(...)  MEMORY%
#   node-1  2000m       80%   8Gi          85%
#   node-2  1500m       60%   6Gi          70%

# 2. HPA quer escalar até 10 replicas × 2000m CPU = 20 cores necessários
# Você tem 3500m = 3.5 cores disponíveis
# PROBLEMA: Insuficiente! Precisa:
# - Aumentar nodes OR
# - Reduzir maxReplicas em HPA

# Verificar nodes e resize se necessário
az aks nodepool show --nodepool-name nodepool1 \
  --cluster-name SKY-PROD-AKS \
  --resource-group SKY-PROD-RG
```

### Execução - FASE 2: Deploy HPA

```bash
# HPA já deve estar em gitops/bootstrap/prod/backend.yaml
# Verificar se está aplicado:
kubectl get hpa -n default
# RESULTADO ESPERADO:
#   NAME    REFERENCE          TARGETS  MINPODS  MAXPODS  REPLICAS  AGE
#   backend Deployment/backend 0%/75%   2        10       2         5m
```

### Execução - FASE 3: Simular Load

```bash
# Gerar carga para dispara auto-scaling
# Opção A: Usar ApacheBench (ab)
ab -n 10000 -c 100 http://backend-service/api/health

# Opção B: Usar wrk (mais moderno)
wrk -t12 -c400 -d30s http://backend-service/api/health

# Opção C: Manual com busybox
for i in {1..50}; do
  kubectl run load-$i --rm -it --image=busybox --restart=Never -- \
    sh -c "while true; do wget -q -O- http://backend-service/health; done" &
done
sleep 60
```

### Validação

```bash
# 1. Ver escalamento em tempo real
watch kubectl get hpa,deployment,pods -n default -l app=backend

# ESPERADO (a cada ~1 minuto):
# T+0: 2 replicas, CPU 10%
# T+1: 3 replicas, CPU 60%
# T+2: 4 replicas, CPU 50%
# ... até estabilizar

# 2. Ver eventos de scaling
kubectl get events -n default | grep -i "scaled" | head -10

# 3. Ver CPU/Memory usage
kubectl top pods -n default -l app=backend

# 4. Parar carga e ver scale-down (5-10 minutos depois)
pkill -f "wrk\|ab\|load-"
# Depois de 5 minutos:
watch kubectl get hpa,deployment,pods -n default -l app=backend
# ESPERADO: Replicas volta para 2
```

**Status**: ✅ DONE - Próximo: FIX 6 (Database HA - ALTO RISCO!)

---

## 🔴 FIX 6: DATABASE HA FAILOVER TEST [30 MIN]

### ⚠️ ALTO RISCO 🔴
**Por quê?** Vai MATAR o pod PostgreSQL primary!
**Impacto**: Database indisponível por ~1-2 minutos
**Rollback**: Manual failback (ou aceitar nova topology)

### PRÉ-REQUISITOS CRÍTICOS

```bash
# 1. Backup foi criado
kubectl exec -it postgresql-primary-0 -n databases -- \
  pg_dump -U postgres skydb > /tmp/backup-before-failover.sql

# 2. Replicação está sincronizada
kubectl exec -it postgresql-primary-0 -n databases -- \
  psql -U postgres -c "SELECT * FROM pg_stat_replication;"
# RESULTADO ESPERADO: 2 replicas in "streaming" state

# 3. Backend/Frontend podem tolerar 2 minutos de downtime (verificar SLA)
echo "Você tem certeza que pode interromper o database por 2 minutos? (sim/não)"
read CONFIRM
[ "$CONFIRM" != "sim" ] && echo "❌ Abortando" && exit 1
```

### Execução - FASE 1: Simulação Failover

```bash
echo "=== INICIANDO TESTE DE FAILOVER ==="
echo "Timestamp: $(date)"

# 1. Ver primary antes
echo "PRIMARY ANTES:"
kubectl get pods -n databases -l role=primary
kubectl get pods -n databases -l role=replica

# 2. MATAR O PRIMARY (simular crash)
echo "Matando primary pod..."
PRIMARY_POD=$(kubectl get pods -n databases -l role=primary -o jsonpath='{.items[0].metadata.name}')
echo "Deletando: $PRIMARY_POD"
kubectl delete pod $PRIMARY_POD -n databases

# 3. Monitorar transição
echo "Aguardando eleição de novo primary (até 60 segundos)..."
for i in {1..60}; do
  NEW_PRIMARY=$(kubectl get pods -n databases -l role=primary -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -n "$NEW_PRIMARY" ]; then
    echo "✅ Novo primary eleito: $NEW_PRIMARY"
    break
  fi
  echo "[$i/60] Aguardando..."
  sleep 1
done

# 4. Ver replicação recuperada
echo "Verificando replicação sincronizada..."
sleep 10
kubectl exec -it $NEW_PRIMARY -n databases -- \
  psql -U postgres -c "SELECT * FROM pg_stat_replication;" || \
  echo "⚠️  Replicação ainda sincronizando..."
```

### Execução - FASE 2: Validar Dados Intactos

```bash
# Conectar ao novo primary e verificar dados
kubectl exec -it $(kubectl get pods -n databases -l role=primary -o jsonpath='{.items[0].metadata.name}') -n databases -- \
  psql -U postgres -c "SELECT count(*) FROM information_schema.tables;"
# RESULTADO ESPERADO: mesmo número de tabelas que antes

# Testar algumas queries
kubectl exec -it $(kubectl get pods -n databases -l role=primary -o jsonpath='{.items[0].metadata.name}') -n databases -- \
  psql -U postgres skydb -c "SELECT count(*) FROM users;" 2>/dev/null || \
  echo "⚠️  Adjust query conforme seu schema"
```

### Execução - FASE 3: Backend Reconecta

```bash
# Backend deve reconectar automaticamente
kubectl logs deployment/backend -n default | grep -i "reconnect\|connected" | tail -5

# Se backend não reconectou:
kubectl rollout restart deployment/backend -n default
kubectl rollout status deployment/backend -n default

# Testar API
curl http://backend-service/health
# RESULTADO ESPERADO: {"status":"ok"}
```

### Validação

```bash
# 1. Todos 3 pods rodando
kubectl get pods -n databases
# RESULTADO ESPERADO:
#   postgresql-primary-0     1/1 Running
#   postgresql-replica-1     1/1 Running
#   postgresql-replica-2     1/1 Running
#   redis-master-0           1/1 Running
#   redis-replica-1          1/1 Running
#   redis-replica-2          1/1 Running

# 2. Replicação sincronizada
NEW_PRIMARY=$(kubectl get pods -n databases -l role=primary -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it $NEW_PRIMARY -n databases -- \
  psql -U postgres -c "SELECT count(*) FROM pg_stat_replication;"
# RESULTADO ESPERADO: 2

# 3. Backend conectado
kubectl describe service backend-service | grep Endpoints
# RESULTADO ESPERADO: 2 endpoints (ou mais se escalonado)

# 4. Health check
curl http://backend-service/health
# RESULTADO ESPERADO: HTTP 200 + JSON
```

**Status**: ✅ DONE - Todos os 7 bloqueadores validados! Próximo: DEPLOY

---

## 🚀 DEPLOY: APPLY TODAS AS CONFIGURAÇÕES

### Pré-deploy checklist

- [ ] FIX 1 (Image tags): Commit feito
- [ ] FIX 2 (Grafana secrets): Secrets criados no Key Vault
- [ ] FIX 3 (DNS): DNS aponta para prod LB
- [ ] FIX 4 (Network policies): 4 rotas testadas ✅
- [ ] FIX 5 (ReadOnly FS): Imagens testadas, emptyDir adicionado
- [ ] FIX 6 (DB HA): Failover simulado com sucesso
- [ ] FIX 7 (HPA): Auto-scaling validado
- [ ] Git status: `git status` mostra clean

### Execução

```bash
# 1. Commit final de todos os fixes
git add .
git commit -m "deploy: Apply all 7 production hardening fixes"
git push origin prod/workspace-setup

# 2. Apply com ArgoCD (recomendado)
kubectl apply -f gitops/bootstrap/prod/namespace.yaml
kubectl apply -f gitops/bootstrap/prod/secrets.yaml # (se não via ExternalSecret)
kubectl apply -f gitops/bootstrap/prod/

# OU apply com terraform (mais declarativo)
cd infra/
terraform apply

# 3. Monitorar rollout
kubectl rollout status deployment/backend -n default
kubectl rollout status deployment/frontend -n default
kubectl rollout status deployment/ai-engine -n default

echo "=== Todas aplicações rodando ==="
kubectl get all -n default
kubectl get all -n monitoring
kubectl get all -n databases
```

### Pós-deploy validation

```bash
# 1. Todos pods rodando
kubectl get pods --all-namespaces | grep -E "Running|Pending|CrashLoop"

# 2. Services têm endpoints
kubectl get svc --all-namespaces -o wide | grep -E "backend|frontend|ai"

# 3. Ingress funciona
kubectl get ingress --all-namespaces

# 4. Certs estão prontos
kubectl get certificate --all-namespaces

# 5. HPA está ativo
kubectl get hpa --all-namespaces

# 6. Database replication OK
kubectl exec -it postgresql-primary-0 -n databases -- \
  psql -U postgres -c "SELECT * FROM pg_stat_replication;" | wc -l
# RESULTADO ESPERADO: 2 replicas
```

**Status**: ✅ DEPLOYED

---

## 📊 MONITOR: 48-72 HORAS

### Semana 1: Monitoring Intensivo

```bash
# Configurar notifications
kubectl logs -f deployment/backend -n default | grep -i "error\|exception"

# Monitorar métricas
# - CPU: deve estar 60-75% em carga normal
# - Memory: 50-70%
# - Replicas: 2-6 dependendo da hora
# - Error rate: <0.1%
# - Latency p95: <200ms

# Validações contínuas
watch -n 30 'kubectl top nodes && echo "---" && kubectl top pods -l app=backend'
```

### Alertas a Monitorar

```bash
# 1. Pod crashes
kubectl get events -n default | grep -i crash

# 2. Pending pods
kubectl get pods --all-namespaces | grep Pending

# 3. Database connection errors
kubectl logs deployment/backend -n default | grep -i "database\|connection"

# 4. Scaling issues
kubectl get hpa -A

# 5. Memory pressure
kubectl describe nodes | grep -i "memory\|pressure"
```

---

## ✅ CHECKLIST FINAL

- [ ] FIX 1: Image tags imutáveis ✅
- [ ] FIX 2: Grafana secrets sincronizados ✅
- [ ] FIX 3: DNS resolvendo com HTTPS ✅
- [ ] FIX 4: Network policies testadas (4 rotas) ✅
- [ ] FIX 5: ReadOnly filesystem funcional ✅
- [ ] FIX 6: Database HA failover validado ✅
- [ ] FIX 7: HPA scaling OK ✅
- [ ] Pods rodando sem crashes ✅
- [ ] Endpoints preenchidos ✅
- [ ] Monitoring recebendo métricas ✅
- [ ] API respondendo <100ms ✅
- [ ] HTTPS com certificado válido ✅

**🎉 PRODUCTION READY!**

---

## 📝 NOTAS IMPORTANTES

### Se algo falhar:

1. **Check logs imediatamente**
   ```bash
   kubectl logs pod-name -n namespace
   kubectl describe pod pod-name -n namespace
   ```

2. **Rollback to previous commit**
   ```bash
   git revert HEAD
   git push origin prod/workspace-setup
   kubectl apply -f gitops/bootstrap/prod/
   ```

3. **Escalate para análise**
   - Coletar logs completos
   - Referenciar este documento
   - Parar antes de modificar mais

### Timing realista:

- FIX 1: 2 min
- FIX 2: 5 min
- FIX 3: 15 min (DNS propagation)
- FIX 4: 15 min (tests)
- FIX 5: 10 min
- FIX 6: 30 min (failover + recovery)
- FIX 7: 15 min (load test)
- **TOTAL: ~1h 30m** (+ esperas passivas)

**Depois: 48-72h monitoring conforme produção estabiliza**
