# 🛠️ REMEDIAÇÕES: PROD vs STAGING - CHECKLIST EXECUTÁVEL

## STATUS ATUAL

**BLOQUEADORES CRÍTICOS ANTES DE DEPLOY**: 7

```
🔴 CRÍTICO    Image tag "latest"              → Fixar para prod-v1.0.0
🔴 CRÍTICO    Secrets Grafana faltando        → Criar no Key Vault
🔴 CRÍTICO    DNS não validado                → Testar resolução
🔴 CRÍTICO    Network Policies podem quebrar  → Testar rotas
🟡 ALTO       ReadOnly filesystem untested    → Testar com docker
🟡 ALTO       Database HA novo/untested       → Validar failover
🟡 MÉDIO      HPA sem validação capacity      → Verificar CPUs
```

---

## ✅ SOLUÇÃO 1: FIXAR IMAGE TAGS

### Problema
```yaml
# PROD atual (ERRADO)
image: skyacrstaging.azurecr.io/sky-poc-backend:latest
#      ↑ Registry staging                     ↑ Mutable!
```

### Impacto
- Sem rastreabilidade de qual imagem está rodando
- Se alguém fizer push de imagem ruim, tudo quebra silenciosamente
- Produção esperava imutabilidade

### Solução
```bash
# Opção A: Usar git SHA (recomendado)
tag: "$(git rev-parse --short HEAD)"  # e.g. abc1234

# Opção B: Usar version semântica
tag: "prod-v1.0.0"

# Opção C: Usar timestamp
tag: "prod-$(date +%Y%m%d-%H%M%S)"  # prod-20250101-145930
```

### Executar

```bash
# 1. Decidir estratégia de tagging
# → RECOMENDAÇÃO: prod-v1.0.0

# 2. Atualizar arquivos prod
sed -i 's/tag: "latest"/tag: "prod-v1.0.0"/' \
  gitops/bootstrap/prod/backend.yaml \
  gitops/bootstrap/prod/frontend.yaml \
  gitops/bootstrap/prod/ai.yaml

# 3. Verificar mudanças
git diff gitops/bootstrap/prod/*.yaml | grep "tag:"

# 4. Commit
git add gitops/bootstrap/prod/
git commit -m "FIX: Atualizar image tags latest → prod-v1.0.0"

# 5. Push
git push origin prod/workspace-setup
```

---

## ✅ SOLUÇÃO 2: CRIAR SECRETS NO AZURE KEY VAULT

### Problema
```yaml
# monitoring.yaml - PROD atual
adminPassword: "${GRAFANA_ADMIN_PASSWORD}"  # ← String literal! Não substituída
#               ↑ Template não resolvido
```

**Impacto**:
- Grafana inicia com password literal = "${GRAFANA_ADMIN_PASSWORD}"
- Ninguém consegue fazer login
- Monitoring 100% quebrado

### Solução: Criar secrets via Azure CLI

```bash
# 1. Verificar qual Key Vault usar
KEY_VAULT_NAME="SKY-PROD-KV"  # Ajustar se necessário

# 2. Criar secrets
az keyvault secret set --vault-name "$KEY_VAULT_NAME" \
  --name grafana-admin-username \
  --value "gustavo.mendonca@thedatafirst.com"

az keyvault secret set --vault-name "$KEY_VAULT_NAME" \
  --name grafana-admin-password \
  --value "jesusteama2026"

# 3. Validar que foram criados
az keyvault secret list --vault-name "$KEY_VAULT_NAME" \
  --query "[?contains(name, 'grafana')]" \
  -o table

# 4. Verificar que ExternalSecrets consegue ler
# (Isso será feito no passo de validação)
```

### Integração com ExternalSecrets

**Opção A: Já existe em monitoring.yaml**
```yaml
externalSecret:
  enabled: true
  secretStoreRef:
    name: azure-keyvault
  data:
    - secretKey: grafana-admin-password
      remoteRef:
        key: grafana-admin-password
```

**Se não existir, adicionar:**
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: grafana-secrets
  namespace: monitoring
spec:
  secretStoreRef:
    name: azure-keyvault
    kind: SecretStore
  target:
    name: grafana-admin-secret
    creationPolicy: Owner
  data:
    - secretKey: username
      remoteRef:
        key: grafana-admin-username
    - secretKey: password
      remoteRef:
        key: grafana-admin-password
```

### Validar integração

```bash
# Depois de deploy
kubectl get externalsecrets -n monitoring
# Deve estar "synced"

kubectl get secret -n monitoring | grep grafana
# Deve ter secret "grafana-admin-secret" ou similar

# Verificar conteúdo (cuidado!)
kubectl get secret grafana-admin-secret -n monitoring -o jsonpath='{.data.password}' | base64 -d
# Deve retornar "jesusteama2026"
```

---

## ✅ SOLUÇÃO 3: VALIDAR DNS

### Problema
```bash
$ nslookup api-workspace-prd.skyfirstlabs.com
# Pode retornar NXDOMAIN ou IP errado
```

**Impacto**:
- Ingress não consegue criar certificado Let's Encrypt
- HTTPS não funciona
- Certificado fica "Pending" indefinidamente

### Solução: Validar DNS antes de deploy

```bash
# 1. Definir domínios esperados
DOMAINS=(
  "api-workspace-prd.skyfirstlabs.com"
  "workspace-prd.skyfirstlabs.com"
)

# 2. Testar cada um
for domain in "${DOMAINS[@]}"; do
  echo "=== Testando $domain ==="
  nslookup "$domain"
  dig "$domain"
  echo ""
done

# 3. Verificar que apontam para prod LoadBalancer
# (Depois que terraform apply criar o LoadBalancer)
terraform -chdir=infra/aks output load_balancer_ip

# 4. Verificar que DNS aponta para esse IP
nslookup api-workspace-prd.skyfirstlabs.com
# Deve retornar <LOAD_BALANCER_IP>
```

### Se DNS não resolver

**Opção A: DNS está em outro registrador (não Azure)**
```bash
# Logar no registrador (GoDaddy, Namecheap, etc)
# Criar A record:
# Name: api-workspace-prd
# Value: <IP do Load Balancer prod>
# TTL: 300

# Esperar 5-10 minutos pelo DNS propagate
nslookup api-workspace-prd.skyfirstlabs.com
```

**Opção B: DNS está em Azure DNS**
```bash
az network dns record-set a add-record \
  --resource-group prod-rg \
  --zone-name skyfirstlabs.com \
  --name api-workspace-prd \
  --ipv4-address <LOAD_BALANCER_IP>

# Validar
az network dns record-set a show \
  --resource-group prod-rg \
  --zone-name skyfirstlabs.com \
  --name api-workspace-prd
```

---

## ✅ SOLUÇÃO 4: TESTAR SECURITY CONTEXT COM IMAGENS

### Problema
```yaml
# PROD - SecurityContext
readOnlyRootFilesystem: true
runAsUser: 1000
```

**Impacto**:
- Backend pode não conseguir escrever logs
- Frontend pode falhar cache
- AI pode quebrar se tenta escrever modelos
- Apps falham com: "Read-only file system" error

### Solução: Testar localmente com docker

```bash
# 1. Testar Backend
echo "=== Testando Backend com ReadOnly ==="
docker run --rm \
  --read-only \
  --user 1000:3000 \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --entrypoint /bin/sh \
  skyacrstaging.azurecr.io/sky-poc-backend:prod-v1.0.0 \
  -c "echo 'test' > /tmp/test.txt && cat /tmp/test.txt"

# Se falhar com "Read-only file system":
# → Precisa adicionar emptyDir tmpfs mount

# 2. Testar Frontend
echo "=== Testando Frontend com ReadOnly ==="
docker run --rm \
  --read-only \
  --user 1000:3000 \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  skyacrstaging.azurecr.io/sky-poc-frontend:prod-v1.0.0 \
  npm start

# 3. Testar AI
echo "=== Testando AI com ReadOnly ==="
docker run --rm \
  --read-only \
  --user 1000:3000 \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  skyacrstaging.azurecr.io/sky-poc-ai:prod-v1.0.0 \
  python app.py
```

### Se falhar: Adicionar emptyDir para /tmp

```yaml
# Em prod/backend.yaml adicionar:
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
```

---

## ✅ SOLUÇÃO 5: VALIDAR CAPACIDADE DO CLUSTER

### Problema
```
Pods escalam para maxReplicas 10, mas cluster só tem espaço para 2
→ Restante fica pending indefinidamente
```

**HPA PROD**:
- Backend: 2-10 replicas × 500m CPU = até 5 CPUs
- Frontend: 2-10 replicas × 200m CPU = até 2 CPUs
- AI: 2-5 replicas × 500m CPU = até 2.5 CPUs
- **Total necessário**: ~10 CPUs só para maxReplicas

### Solução: Validar recursos do cluster

```bash
# 1. Ver nodes disponível
kubectl get nodes -o wide

# 2. Ver capacidade total
kubectl top nodes

# 3. Calcular espaço disponível
kubectl describe nodes | grep -E "Name:|Allocated resources:|cpu"

# 4. Ver pods pending (se houver)
kubectl get pods --all-namespaces --field-selector=status.phase=Pending

# 5. Verificar se precisa escalar nodes
# No Azure AKS:
az aks nodepool list --resource-group prod-rg --cluster-name prod-aks
az aks nodepool scale --resource-group prod-rg \
  --cluster-name prod-aks \
  --name nodepool1 \
  --node-count 5  # Aumentar se necessário
```

### Resultado esperado
```bash
$ kubectl top nodes
NAME                                    CPU(cores)   CPU%   MEMORY(Mi)   MEMORY%
aks-nodepool1-12345678-vmss000000      500m         5%     1024Mi       10%
aks-nodepool1-12345678-vmss000001      480m         4%     1152Mi       11%

# → Espaço suficiente para scaling!
```

---

## ✅ SOLUÇÃO 6: TESTAR DATABASE HA FAILOVER

### Problema
```yaml
# databases-ha.yaml - NOVO e nunca testado
PostgreSQL: 1 Primary + 2 Replicas
Redis: 1 Master + 2 Replicas + Sentinel
```

**Impacto**:
- Replicação pode não sincronizar
- Failover pode não funcionar
- Backend pode não conectar a new primary
- Data pode ser perdida

### Solução: Testar manualmente

```bash
# 1. Deploy database-ha.yaml
kubectl apply -f gitops/bootstrap/prod/databases-ha.yaml

# 2. Esperar pods ficarem ready
kubectl wait --for=condition=ready pod \
  -l app=postgresql \
  -n databases \
  --timeout=300s

# 3. Verificar replicação
kubectl exec -it postgresql-primary-0 -n databases -- \
  psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Deve mostrar 2 replicas sincronizadas

# 4. Testar failover: MATAR o primary
kubectl delete pod postgresql-primary-0 -n databases

# 5. Esperar 30 segundos
sleep 30

# 6. Verificar que uma replica virou primary
kubectl get pods -n databases -l app=postgresql -o wide

# 7. Testar backup
kubectl get cronjob -n databases

# 8. Testar connection pooling
# Aplicação deve conseguir conectar ao novo primary automaticamente
# (Validar com: kubectl logs backend-pod)
```

### Resultado esperado
```
PostgreSQL replication: ✅ 2 replicas synced
Primary failover: ✅ New primary eleito em <30s
Connection pool failover: ✅ Backend reconecta automaticamente
```

---

## ✅ SOLUÇÃO 7: REVISAR NETWORK POLICIES ROTAS

### Problema
```yaml
# prod/network-policies.yaml - NOVO
default: DENY all traffic
→ Pode bloquear conexões necessárias
```

**Impacto**:
- Backend não consegue conectar ao database
- Loki não consegue scrape logs dos pods
- Prometheus não consegue scrape métricas

### Solução: Validar cada rota necessária

```bash
# 1. Listar todas as network policies
kubectl get networkpolicies -A

# 2. Testar rotas críticas
# Rota 1: Backend → PostgreSQL
kubectl exec -it backend-pod -- \
  psql -h postgresql.databases -U postgres -d postgres -c "SELECT 1;"
# Deve retornar: 1

# Rota 2: Loki → Backend logs
kubectl exec -it loki-pod -- \
  curl http://backend.default:8000/health
# Deve retornar 200 OK

# Rota 3: Prometheus → Prometheus targets
kubectl exec -it prometheus-pod -- \
  curl http://prometheus.monitoring:9090/api/v1/targets
# Deve retornar JSON

# Rota 4: Frontend → Backend API
kubectl exec -it frontend-pod -- \
  curl http://backend.default:8000/api/health
# Deve retornar 200 OK

# 3. Se alguma rota falhar:
# Revisar network-policies.yaml
# Adicionar NetworkPolicy que permite rota específica
```

### Template NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-backend-to-postgres
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
      ports:
        - protocol: TCP
          port: 5432
```

---

## 📋 CHECKLIST DE EXECUÇÃO

### PRÉ-FLIGHT (30 min)

- [ ] **FIX 1**: Atualizar image tags latest → prod-v1.0.0
  ```bash
  cd gitops/bootstrap/prod/
  sed -i 's/tag: "latest"/tag: "prod-v1.0.0"/' *.yaml
  git add . && git commit -m "FIX: Image tags"
  ```

- [ ] **FIX 2**: Criar secrets no Key Vault
  ```bash
  az keyvault secret set --vault-name SKY-PROD-KV \
    --name grafana-admin-password --value "jesusteama2026"
  ```

- [ ] **FIX 3**: Validar DNS
  ```bash
  nslookup api-workspace-prd.skyfirstlabs.com
  # Deve retornar IP prod (após terraform apply)
  ```

- [ ] **FIX 4**: Testar SecurityContext com docker
  ```bash
  docker run --rm --read-only \
    skyacrstaging.azurecr.io/sky-poc-backend:prod-v1.0.0 \
    echo "test" > /tmp/test.txt
  # Deve suceder ou indicar precisa emptyDir
  ```

- [ ] **FIX 5**: Validar cluster tem 20+ CPUs
  ```bash
  kubectl top nodes
  # Deve mostrar espaço suficiente
  ```

- [ ] **FIX 6**: Testar Database HA failover
  ```bash
  kubectl apply -f gitops/bootstrap/prod/databases-ha.yaml
  kubectl delete pod postgresql-primary-0
  # Deve eleitar novo primary em <30s
  ```

- [ ] **FIX 7**: Revisar Network Policies rotas
  ```bash
  kubectl exec -it backend-pod -- \
    psql -h postgresql.databases -U postgres -c "SELECT 1;"
  # Deve conectar sem erro
  ```

### DEPLOY (10 min)

- [ ] **DEPLOY 1**: Terraform apply
  ```bash
  terraform -chdir=infra/aks apply -var-file=terraform.tfvars.prod
  ```

- [ ] **DEPLOY 2**: Apply bootstrap files
  ```bash
  kubectl apply -f gitops/bootstrap/prod/
  ```

- [ ] **DEPLOY 3**: Monitor ArgoCD
  ```bash
  argocd app list
  argocd app wait sky-backend-prod
  ```

### PÓS-DEPLOY (15 min)

- [ ] **VALIDATE 1**: Todos pods rodando
  ```bash
  kubectl get pods -A | grep -v Running
  # Não deve retornar nada
  ```

- [ ] **VALIDATE 2**: Health checks OK
  ```bash
  curl https://api-workspace-prd.skyfirstlabs.com/health
  # HTTP 200
  ```

- [ ] **VALIDATE 3**: Grafana login funciona
  ```bash
  # Browser: https://grafana-workspace-prd.skyfirstlabs.com
  # User: gustavo.mendonca@thedatafirst.com
  # Pass: jesusteama2026
  ```

- [ ] **VALIDATE 4**: Database replication OK
  ```bash
  kubectl exec -it postgresql-primary -- \
    psql -U postgres -c "SELECT * FROM pg_stat_replication;"
  # Deve mostrar 2 replicas
  ```

---

## 🚀 PRÓXIMOS PASSOS

1. **Executar FIX 1-7 em ordem** (takes ~1 hour)
2. **Executar DEPLOY 1-3** (takes ~10 min)
3. **Executar VALIDATE 1-4** (takes ~15 min)
4. **Monitorar 48h antes de considerar stable**

**Tempo total**: ~2-3 horas de implementação + 48h de monitoramento

---

**ÚLTIMA ATUALIZAÇÃO**: 2025-01-15
**STATUS**: Pronto para execução
