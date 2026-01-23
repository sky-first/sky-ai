# 🛠️ COMO RESOLVER: GUIA PRÁTICO PASSO-A-PASSO

## 🔴 [1/7] IMAGE TAG "latest" → FIXAR PARA VERSÃO IMUTÁVEL

### Problema
```yaml
# ATUAL (ERRADO - mutável)
image: skyacrstaging.azurecr.io/sky-poc-backend:latest
```

### Solução 1: Usar Git SHA (RECOMENDADO)
```bash
# 1. Ir para diretório prod
cd gitops/bootstrap/prod

# 2. Obter SHA do commit atual
GIT_SHA=$(git rev-parse --short HEAD)
echo "Git SHA: $GIT_SHA"

# 3. Atualizar tags em todos os arquivos
sed -i.bak "s/tag: \"latest\"/tag: \"$GIT_SHA\"/" *.yaml

# 4. Verificar mudanças
git diff *.yaml | grep tag

# 5. Commit
git add *.yaml
git commit -m "fix: Image tags latest → $GIT_SHA (imutável)"
git push origin prod/workspace-setup
```

### Solução 2: Usar Versão Semântica
```bash
cd gitops/bootstrap/prod

# Versão específica
TAG="prod-v1.0.0"
sed -i.bak "s/tag: \"latest\"/tag: \"$TAG\"/" *.yaml

# Verificar
grep "tag:" *.yaml

# Commit
git add *.yaml
git commit -m "fix: Image tags latest → $TAG"
git push origin prod/workspace-setup
```

### Validação
```bash
# 1. Verificar tags atualizadas
grep -r "tag:" gitops/bootstrap/prod/ | grep -v latest

# 2. Confirmar que nenhuma tag é "latest"
grep "latest" gitops/bootstrap/prod/*.yaml
# Deve retornar NADA (exit code 1 = sucesso)

# 3. Listar tags finais
echo "=== Tags após update ==="
grep "tag:" gitops/bootstrap/prod/*.yaml
```

---

## 🔴 [2/7] SECRETS GRAFANA FALTANDO

### Problema
```yaml
# monitoring.yaml - ATUAL
adminPassword: "${GRAFANA_ADMIN_PASSWORD}"  # ← Literal string, não substituída!
```

### Solução: Criar Secrets no Azure Key Vault

```bash
# 1. Definir Key Vault
KEY_VAULT="SKY-PROD-KV"

# Validar que Key Vault existe
az keyvault show --name "$KEY_VAULT" --query id
# Deve retornar ID, não erro

# 2. Criar secret: grafana-admin-username
az keyvault secret set \
  --vault-name "$KEY_VAULT" \
  --name "grafana-admin-username" \
  --value "gustavo.mendonca@thedatafirst.com"

# 3. Criar secret: grafana-admin-password
az keyvault secret set \
  --vault-name "$KEY_VAULT" \
  --name "grafana-admin-password" \
  --value "jesusteama2026"

# 4. Validar que foram criados
az keyvault secret list --vault-name "$KEY_VAULT" \
  --query "[?contains(name, 'grafana')] | [].name" \
  -o tsv
# Deve mostrar:
#   grafana-admin-username
#   grafana-admin-password

# 5. Testar leitura
az keyvault secret show \
  --vault-name "$KEY_VAULT" \
  --name "grafana-admin-password" \
  --query value -o tsv
# Deve retornar: jesusteama2026
```

### Integração com Kubernetes (ExternalSecrets)

```bash
# 1. Verificar que monitoring.yaml tem ExternalSecret
grep -A 5 "externalSecret:" gitops/bootstrap/prod/monitoring.yaml

# 2. Se NÃO tiver, adicionar em monitoring.yaml
# ANTES do deployment Grafana, add:

cat >> gitops/bootstrap/prod/monitoring-secrets.yaml << 'EOF'
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: grafana-admin-secret
  namespace: monitoring
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: azure-keyvault
    kind: SecretStore
  target:
    name: grafana-secret
    creationPolicy: Owner
    template:
      engineVersion: v2
      data:
        admin-username: "{{ .username }}"
        admin-password: "{{ .password }}"
  data:
    - secretKey: username
      remoteRef:
        key: grafana-admin-username
    - secretKey: password
      remoteRef:
        key: grafana-admin-password
EOF

# 3. Commit
git add gitops/bootstrap/prod/monitoring-secrets.yaml
git commit -m "feat: ExternalSecret para Grafana credentials"
git push origin prod/workspace-setup
```

### Validação (após kubectl apply)

```bash
# Depois de deploy, validar que ExternalSecret sincronizou

# 1. Verificar ExternalSecret status
kubectl get externalsecrets -n monitoring
# Status deve ser "SecretSynced"

# 2. Verificar que secret foi criado
kubectl get secret grafana-secret -n monitoring -o yaml

# 3. Decodificar password
kubectl get secret grafana-secret -n monitoring \
  -o jsonpath='{.data.admin-password}' | base64 -d
# Deve retornar: jesusteama2026

# 4. Verificar que Grafana está usando a secret
kubectl get deployment grafana -n monitoring -o yaml | \
  grep -A 5 "env:" | grep -i password
```

---

## 🔴 [3/7] DNS NÃO VALIDADO

### Problema
```
HTTPS não funciona porque:
1. DNS não aponta para prod Load Balancer IP
2. Cert-Manager não consegue validar ownership
3. Let's Encrypt certificate não é criado
```

### Solução: Validar e Configurar DNS

```bash
# ============================================
# FASE 1: Obter Load Balancer IP de PROD
# ============================================

# 1. Fazer terraform apply
cd infra/aks
terraform apply -var-file=terraform.tfvars.prod

# 2. Obter IP do Load Balancer
LB_IP=$(terraform output load_balancer_ip | tr -d '"')
echo "Load Balancer IP: $LB_IP"

# ============================================
# FASE 2: Validar DNS ATUALMENTE
# ============================================

# 3. Testar resolução DNS ANTES da mudança
nslookup api-workspace-prd.skyfirstlabs.com
# Pode retornar:
#   - NXDOMAIN (não existe)
#   - IP antigo (apontando para staging)
#   - IP correto (já está ok)

# 4. Obter IP atual
CURRENT_IP=$(dig +short api-workspace-prd.skyfirstlabs.com)
echo "IP ATUAL: $CURRENT_IP"
echo "IP ESPERADO: $LB_IP"

# ============================================
# FASE 3: CONFIGURAR DNS (se diferente)
# ============================================

# Se DNS está apontando para lugar errado:
# OPÇÃO A: DNS em Azure DNS
if [ "$CURRENT_IP" != "$LB_IP" ]; then
  echo "Atualizando DNS..."
  
  az network dns record-set a add-record \
    --resource-group prod-rg \
    --zone-name skyfirstlabs.com \
    --name api-workspace-prd \
    --ipv4-address "$LB_IP"
fi

# OPÇÃO B: DNS em registrador externo (GoDaddy, Namecheap, etc)
# 1. Logar em https://domains.google.com (ou seu registrador)
# 2. Ir para DNS settings
# 3. Encontrar registro: api-workspace-prd.skyfirstlabs.com
# 4. Alterar valor para: $LB_IP
# 5. Salvar e esperar 5-10 minutos

# ============================================
# FASE 4: VALIDAR DNS MUDANÇA PROPAGADA
# ============================================

# 6. Esperar propagação (pode levar 5-10 min)
echo "Aguardando propagação DNS (5-10 min)..."
sleep 60

# 7. Testar resolução até funcionar
for i in {1..30}; do
  IP=$(dig +short api-workspace-prd.skyfirstlabs.com)
  echo "[$i/30] Tentativa: $IP"
  
  if [ "$IP" == "$LB_IP" ]; then
    echo "✅ DNS propagado! Resolvendo para: $IP"
    break
  fi
  
  sleep 10
done

# ============================================
# FASE 5: TESTAR HTTPS
# ============================================

# 8. Testar que HTTPS funciona
curl -I https://api-workspace-prd.skyfirstlabs.com
# Esperado: HTTP/1.1 200 OK ou 301/302 redirect

# 9. Verificar certificado
openssl s_client -connect api-workspace-prd.skyfirstlabs.com:443 \
  -servername api-workspace-prd.skyfirstlabs.com
# Procure por: "Issuer: C = US, O = Let's Encrypt"
```

### Resumo de Problemas Comuns

```bash
# Se receber: "connection refused"
# → Load Balancer não está pronto ainda
# → Esperar terraform apply completar

# Se receber: "certificate verify failed"
# → Certificado não foi criado ainda
# → Validar que Cert-Manager está rodando:
kubectl get pods -n cert-manager

# Se receber: "NXDOMAIN"
# → DNS ainda não foi propagado
# → Esperar 10-15 minutos mais

# Se receber: "timeout"
# → DNS aponta para IP errado
# → Validar: dig api-workspace-prd.skyfirstlabs.com
```

---

## 🔴 [4/7] NETWORK POLICIES UNTESTED

### Problema
```
Network policies podem bloquear rotas necessárias:
- Backend → PostgreSQL (database)
- Loki → Pod logs (observability)
- Prometheus → Scrape targets (monitoring)
- Frontend → Backend API (application)
```

### Solução: Testar Cada Rota

```bash
# ============================================
# Preparação: Deploy das policies
# ============================================

# 1. Deploy network policies (PRIMEIRO SEM DEFAULT DENY)
kubectl apply -f gitops/bootstrap/prod/network-policies.yaml

# 2. Listar policies criadas
kubectl get networkpolicies -A

# ============================================
# TESTE 1: Backend → PostgreSQL
# ============================================

# 3. Teste de conexão: Backend precisa falar com PostgreSQL
BACKEND_POD=$(kubectl get pods -n default \
  -l app=backend -o jsonpath='{.items[0].metadata.name}')

kubectl exec -it "$BACKEND_POD" -n default -- \
  psql -h postgresql.databases.svc.cluster.local \
       -U postgres \
       -d postgres \
       -c "SELECT 1;"

# Esperado: "1" (sucesso)
# Erro esperado se bloqueado: "could not translate host name"

# ============================================
# TESTE 2: Loki → Logs dos Pods
# ============================================

# 4. Teste: Loki precisa fazer scrape de logs
LOKI_POD=$(kubectl get pods -n monitoring \
  -l app=loki -o jsonpath='{.items[0].metadata.name}')

kubectl exec -it "$LOKI_POD" -n monitoring -- \
  curl http://backend.default:8000/api/prom/push \
    -H "Content-Type: application/json" \
    -d '{"streams":[{"stream":{"job":"test"},"values":[["1234567890000000000","test"]]}]}'

# Esperado: HTTP 204 ou similar
# Se bloqueado: "Connection refused" ou timeout

# ============================================
# TESTE 3: Prometheus → Scrape Metrics
# ============================================

# 5. Teste: Prometheus precisa scrape métricas
PROMETHEUS_POD=$(kubectl get pods -n monitoring \
  -l app=prometheus -o jsonpath='{.items[0].metadata.name}')

kubectl exec -it "$PROMETHEUS_POD" -n monitoring -- \
  curl http://backend.default:8000/metrics

# Esperado: Métricas Prometheus (linhas com #)
# Se bloqueado: "Connection refused"

# ============================================
# TESTE 4: Frontend → Backend API
# ============================================

# 6. Teste: Frontend precisa falar com Backend
FRONTEND_POD=$(kubectl get pods -n default \
  -l app=frontend -o jsonpath='{.items[0].metadata.name}')

kubectl exec -it "$FRONTEND_POD" -n default -- \
  curl http://backend.default:8000/health

# Esperado: {"status": "ok"} ou similar
# Se bloqueado: "Connection refused"

# ============================================
# RESUMO DOS TESTES
# ============================================

# 7. Script automático (all in one)
cat > /tmp/test-network-policies.sh << 'EOFTEST'
#!/bin/bash

echo "=== TESTANDO NETWORK POLICIES ==="

# Test 1: Backend → PostgreSQL
echo ""
echo "[1/4] Backend → PostgreSQL"
BACKEND_POD=$(kubectl get pods -n default \
  -l app=backend -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it "$BACKEND_POD" -n default -- \
  psql -h postgresql.databases.svc.cluster.local \
       -U postgres -c "SELECT 1;" 2>&1 | grep -q "1" && echo "✅ OK" || echo "❌ BLOQUEADO"

# Test 2: Loki → Pods
echo ""
echo "[2/4] Loki → Pod Logs"
LOKI_POD=$(kubectl get pods -n monitoring \
  -l app=loki -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it "$LOKI_POD" -n monitoring -- \
  curl -s http://backend.default:8000/health | grep -q "ok" && echo "✅ OK" || echo "❌ BLOQUEADO"

# Test 3: Prometheus → Metrics
echo ""
echo "[3/4] Prometheus → Metrics"
PROMETHEUS_POD=$(kubectl get pods -n monitoring \
  -l app=prometheus -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it "$PROMETHEUS_POD" -n monitoring -- \
  curl -s http://backend.default:8000/metrics | grep -q "HELP" && echo "✅ OK" || echo "❌ BLOQUEADO"

# Test 4: Frontend → Backend
echo ""
echo "[4/4] Frontend → Backend API"
FRONTEND_POD=$(kubectl get pods -n default \
  -l app=frontend -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it "$FRONTEND_POD" -n default -- \
  curl -s http://backend.default:8000/health | grep -q "ok" && echo "✅ OK" || echo "❌ BLOQUEADO"

echo ""
echo "=== FIM DOS TESTES ==="
EOFTEST

chmod +x /tmp/test-network-policies.sh
/tmp/test-network-policies.sh
```

### Se Alguma Rota Estiver Bloqueada

```bash
# Ver logs de deny (se usando Calico)
kubectl logs -n kube-system -l k8s-app=calico-node --tail=50 | grep DENY

# Adicionar policy permissiva (exemplo: Backend → PostgreSQL)
cat > /tmp/allow-backend-to-postgres.yaml << 'EOF'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-backend-to-postgres
  namespace: default
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Egress
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: postgresql
          namespaceSelector:
            matchLabels:
              name: databases
      ports:
        - protocol: TCP
          port: 5432
    # Permitir DNS
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
EOF

kubectl apply -f /tmp/allow-backend-to-postgres.yaml

# Retest
# (comando do teste acima)
```

---

## 🟡 [5/7] READONLY FILESYSTEM UNTESTED

### Problema
```
readOnlyRootFilesystem: true pode quebrar apps que escrevem em:
- /tmp
- /var/cache
- /app (diretório da app)
```

### Solução: Testar Imagens com ReadOnly

```bash
# ============================================
# TESTE 1: Backend
# ============================================

echo "=== Testando BACKEND com ReadOnly ==="

docker run --rm \
  --read-only \
  --user 1000:3000 \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --entrypoint /bin/sh \
  skyacrstaging.azurecr.io/sky-poc-backend:prod-v1.0.0 \
  -c "echo 'test' > /tmp/test.txt && cat /tmp/test.txt"

# Esperado: 
#   ✅ "test" (sucesso - consegue escrever em /tmp)
# Ou erro:
#   ❌ "Read-only file system" (precisa emptyDir mount)

# ============================================
# TESTE 2: Frontend
# ============================================

echo "=== Testando FRONTEND com ReadOnly ==="

docker run --rm \
  --read-only \
  --user 1000:3000 \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  skyacrstaging.azurecr.io/sky-poc-frontend:prod-v1.0.0 \
  npm --version

# Esperado: npm version (sucesso)
# Erro: Significa que algo precisa escrever

# ============================================
# TESTE 3: AI Engine
# ============================================

echo "=== Testando AI com ReadOnly ==="

docker run --rm \
  --read-only \
  --user 1000:3000 \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  skyacrstaging.azurecr.io/sky-poc-ai:prod-v1.0.0 \
  python --version

# Esperado: python version (sucesso)
# Erro: Significa que algo precisa escrever

# ============================================
# SE ALGUMA FALHAR: Adicionar emptyDir
# ============================================

# Em prod/backend.yaml, adicionar:
cat >> /tmp/emptydir-fix.yaml << 'EOF'
spec:
  template:
    spec:
      containers:
        - name: backend
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: cache
              mountPath: /app/cache  # Se necessário
      volumes:
        - name: tmp
          emptyDir: {}
        - name: cache
          emptyDir: {}
EOF

# Aplicar a mudança em backend.yaml:
# 1. Copiar o spec.template.spec.containers[0].volumeMounts acima
# 2. Adicionar em backend.yaml no container backend
# 3. Copiar volumes secção em spec.template.spec
# 4. Commit e push

# Após mudança, retest:
docker run --rm \
  --read-only \
  --user 1000:3000 \
  -v /tmp:/tmp \
  skyacrstaging.azurecr.io/sky-poc-backend:prod-v1.0.0 \
  bash -c "echo 'test' > /tmp/test.txt"
# Esperado: ✅ Sucesso
```

---

## 🟡 [6/7] DATABASE HA NOVO/UNTESTED

### Problema
```
PostgreSQL + Redis HA nunca foram testados:
- Replicação pode não sincronizar
- Failover pode não eleger novo primary
- Backups podem não rodar
- Connection pooling pode quebrar
```

### Solução: Testar Failover Manualmente

```bash
# ============================================
# FASE 1: Deploy Database HA
# ============================================

# 1. Deploy
kubectl apply -f gitops/bootstrap/prod/databases-ha.yaml

# 2. Esperar pods ficarem ready
kubectl wait --for=condition=ready pod \
  -l app=postgresql \
  -n databases \
  --timeout=300s

echo "Pods ready!"

# ============================================
# FASE 2: Validar Replicação
# ============================================

# 3. Conectar ao primary e verificar replicas
kubectl exec -it postgresql-primary-0 -n databases -- \
  psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Esperado output:
#  usename | application_name | client_addr | state | sync_state
# ---------+------------------+-------------+-------+----------
#  replication | walreceiver | 10.x.x.x | streaming | async
#  replication | walreceiver | 10.x.x.y | streaming | async

# ============================================
# FASE 3: TESTAR FAILOVER
# ============================================

# 4. Preparação: Anotar primary antes de matar
echo "PRIMARY ANTES:"
kubectl get pods -n databases -l app=postgresql -o wide

# 5. MATAR o primary
echo "Matando primary..."
kubectl delete pod postgresql-primary-0 -n databases

# 6. Esperar
echo "Aguardando 30 segundos..."
sleep 30

# 7. Verificar novo primary foi eleito
echo "VERIFICANDO NOVO PRIMARY:"
kubectl get pods -n databases -l app=postgresql -o wide

# Esperado: Uma das replicas virou primary
# Pode aparecer como: postgresql-primary-0 (novo) ou postgresql-replica-X

# ============================================
# FASE 4: TESTAR CONEXÃO
# ============================================

# 8. Conectar ao novo primary e verificar que funciona
kubectl exec -it $(kubectl get pods -n databases -l app=postgresql \
  -o jsonpath='{.items[0].metadata.name}') -n databases -- \
  psql -U postgres -c "SELECT version();"

# Esperado: PostgreSQL version info

# ============================================
# FASE 5: TESTAR BACKUPS
# ============================================

# 9. Listar cronjobs
kubectl get cronjob -n databases

# 10. Verificar último backup
kubectl get jobs -n databases | grep backup

# 11. Se nenhum backup rodou ainda, rodar manualmente
kubectl create job --from=cronjob/postgresql-backup \
  test-backup -n databases

# 12. Esperar backup completar
kubectl wait --for=condition=complete job/test-backup \
  -n databases --timeout=300s

# 13. Verificar se backup foi criado
kubectl exec -it postgresql-primary-0 -n databases -- \
  ls -lh /backups/

# Esperado: arquivo postgresql_backup_*.sql com tamanho > 0

# ============================================
# FASE 6: TESTAR RESTAURAÇÃO DE BACKUP
# ============================================

# 14. Criar database de teste
kubectl exec -it postgresql-primary-0 -n databases -- \
  psql -U postgres -c "CREATE DATABASE test_db AS TEMPLATE postgres;"

# 15. Inserir dados
kubectl exec -it postgresql-primary-0 -n databases -- \
  psql -U postgres test_db -c "CREATE TABLE test (id SERIAL, data TEXT); INSERT INTO test (data) VALUES ('hello');"

# 16. Fazer backup
kubectl create job --from=cronjob/postgresql-backup \
  backup-with-data -n databases

kubectl wait --for=condition=complete job/backup-with-data \
  -n databases --timeout=300s

# 17. Simular perda de dados
kubectl exec -it postgresql-primary-0 -n databases -- \
  psql -U postgres test_db -c "DROP TABLE test;"

# 18. Restaurar de backup
BACKUP_FILE=$(kubectl exec -it postgresql-primary-0 -n databases -- \
  ls -t /backups/ | head -1)

kubectl exec -it postgresql-primary-0 -n databases -- \
  psql -U postgres < "/backups/$BACKUP_FILE"

# 19. Validar restauração
kubectl exec -it postgresql-primary-0 -n databases -- \
  psql -U postgres test_db -c "SELECT * FROM test;"

# Esperado: dados restaurados

# ============================================
# RESUMO
# ============================================

echo ""
echo "=== VALIDAÇÃO DATABASE HA ==="
echo "✅ Replicação sincronizando: $(kubectl exec -it postgresql-primary-0 -n databases -- psql -U postgres -c 'SELECT count(*) FROM pg_stat_replication;' | grep -o '[0-9]' | head -1) replicas"
echo "✅ Failover funcionando"
echo "✅ Backups rodando"
echo "✅ Restauração funcionando"
```

---

## 🟡 [7/7] HPA SEM VALIDAÇÃO CAPACITY

### Problema
```
HPA pode escalar para maxReplicas:
- Backend: 2-10 replicas = até 5 CPUs necessários
- Frontend: 2-10 replicas = até 2 CPUs necessários
- AI: 2-5 replicas = até 2.5 CPUs necessários
TOTAL: ~10 CPUs mínimo necessário

Se cluster não tiver espaço, pods ficam pending indefinidamente
```

### Solução: Validar Capacity e Escalar se Necessário

```bash
# ============================================
# FASE 1: VER CAPACIDADE ATUAL
# ============================================

# 1. Ver nodes
kubectl get nodes
kubectl get nodes -o wide

# 2. Ver uso atual
echo "=== USO ATUAL ==="
kubectl top nodes

# Esperado output:
# NAME                                  CPU(cores)   CPU%   MEMORY(Mi)   MEMORY%
# aks-nodepool1-12345678-vmss000000      500m         5%     1024Mi       10%
# aks-nodepool1-12345678-vmss000001      480m         4%     1152Mi       11%

# 3. Ver capacidade alocável
echo ""
echo "=== CAPACIDADE ALOCÁVEL ==="
kubectl describe nodes | grep -A 5 "Allocatable"

# Esperado: mostrar CPUs e Memory disponível

# ============================================
# FASE 2: CALCULAR NECESSÁRIO PARA HPA
# ============================================

# 4. Calcular espaço necessário para maxReplicas
# Backend: 10 replicas × 500m = 5000m (5 CPUs)
# Frontend: 10 replicas × 200m = 2000m (2 CPUs)
# AI: 5 replicas × 500m = 2500m (2.5 CPUs)
# TOTAL: ~10 CPUs necessário para maxReplicas

echo ""
echo "=== REQUIREMENTS PARA HPA ==="
echo "Backend: 10 × 500m = 5000m (5 CPUs)"
echo "Frontend: 10 × 200m = 2000m (2 CPUs)"
echo "AI: 5 × 500m = 2500m (2.5 CPUs)"
echo "TOTAL NECESSÁRIO: ~10 CPUs (com margem: 12-15 CPUs recomendado)"

# ============================================
# FASE 3: VALIDAR SE TEM ESPAÇO
# ============================================

# 5. Calcular capacidade total vs necessário
TOTAL_CAPACITY=$(kubectl describe nodes | grep "cpu:" | \
  awk '{print $2}' | sed 's/m//g' | awk '{sum+=$1} END {print sum}')

echo ""
echo "Capacidade total: ${TOTAL_CAPACITY}m = $(echo "scale=1; $TOTAL_CAPACITY/1000" | bc) CPUs"
echo "Necessário: 10000m = 10 CPUs"

if [ $TOTAL_CAPACITY -gt 15000 ]; then
  echo "✅ Espaço SUFICIENTE para HPA"
else
  echo "❌ ESPAÇO INSUFICIENTE - precisa escalar cluster"
fi

# ============================================
# FASE 4: SE INSUFICIENTE - ESCALAR CLUSTER
# ============================================

# 6. Se não tiver espaço, escalar nodes no Azure
RESOURCE_GROUP="prod-rg"
CLUSTER_NAME="prod-aks"
NODEPOOL_NAME="nodepool1"

# Aumentar para 5 nodes (ex: 3 → 5)
echo ""
echo "Escalando cluster AKS..."
az aks nodepool scale \
  --resource-group "$RESOURCE_GROUP" \
  --cluster-name "$CLUSTER_NAME" \
  --name "$NODEPOOL_NAME" \
  --node-count 5

# 7. Esperar nodes ficarem ready
echo "Aguardando nodes ficarem ready (5-10 min)..."
kubectl wait --for=condition=Ready node --all --timeout=600s

# 8. Verificar que escalou
kubectl get nodes
kubectl top nodes

# ============================================
# FASE 5: TESTAR HPA DEPOIS
# ============================================

# 9. Deploy apps com HPA
kubectl apply -f gitops/bootstrap/prod/

# 10. Causar stress para testar scaling
kubectl run -it --image=busybox /bin/sh --rm -- \
  wget --spider -q http://backend.default:8000/health

# 11. Observar pods escalando
watch kubectl get pods -n default -l app=backend

# Esperado: replicas aumentando gradualmente até 10

# 12. Quando estresse passar, deve desescalar
# (depois de ~5 minutos sem uso)

echo ""
echo "✅ HPA funcionando! Pods escalaram para $(kubectl get pods -n default -l app=backend --no-headers | wc -l) replicas"
```

---

## ✅ CHECKLIST FINAL DE EXECUÇÃO

```bash
# Executar em ordem:
☐ [1/7] FIX Image Tags                    (~5 min)
☐ [2/7] Criar Secrets Grafana             (~5 min)
☐ [3/7] Validar DNS                       (~15 min - com propagação)
☐ [4/7] Testar Network Policies           (~15 min)
☐ [5/7] Testar SecurityContext            (~10 min)
☐ [6/7] Testar Database HA Failover       (~30 min)
☐ [7/7] Validar HPA Capacity              (~10 min)

TOTAL: ~90 minutos

Após completar as 7 ações:
☐ terraform apply
☐ kubectl apply -f gitops/bootstrap/prod/
☐ Validar 48-72 horas
☐ Go/NoGo para staging → production
```

---

## 🆘 TROUBLESHOOTING

| Erro | Causa | Solução |
|------|-------|---------|
| `Connection refused` | App não está rodando | `kubectl get pods`, verificar logs |
| `Read-only file system` | readOnly=true + app tenta escrever | Adicionar emptyDir para /tmp |
| `NXDOMAIN` | DNS não propagou | Esperar 10-15 min, testar com `dig` |
| `CertificateNotReady` | Cert-Manager não conseguiu validar | Verificar DNS: `nslookup` |
| `ImagePullBackOff` | Imagem não existe na registry | Verificar `tag:` e registry |
| `Pod Pending` | Cluster sem espaço | `kubectl top nodes`, escalar |
| `Network unreachable` | Network Policies bloqueando | Testar rotas, revisar policies |
| `Failover não funcionou` | Database HA mal configurado | Verificar `pg_stat_replication` |
