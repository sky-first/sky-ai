# 📚 Production Runbook - Sky Workspace Produção

**Versão**: 1.0  
**Data**: 22 de janeiro de 2026  
**Cluster**: sky-aks-prod (eastus2)  
**Domínios**: workspace-prd.skyfirstlabs.com, api-workspace-prd.skyfirstlabs.com, workspace-prd-ai.skyfirstlabs.com

---

## 🚀 Deployment Produção

### Pré-requisitos
```bash
# Verificar conexão ao cluster
kubectl cluster-info
kubectl get nodes

# Verificar ArgoCD
argocd login <argocd-server> --username admin
argocd app list
```

### Deploy Initial (primeira vez)
```bash
# 1. Aplicar manifests de segurança
argocd app sync sky-infra-secrets-prod

# 2. Aplicar Cert-Manager
argocd app sync sky-cert-manager-prod

# 3. Aguardar Cert-Manager ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=cert-manager -n cert-manager --timeout=300s

# 4. Aplicar Ingress
kubectl apply -f gitops/bootstrap/prod/ingress.yaml -n prod

# 5. Aplicar aplicações
argocd app sync sky-backend-prod
argocd app sync sky-frontend-prod
argocd app sync sky-ai-prod

# 6. Aplicar Databases
argocd app sync sky-databases-prod

# 7. Aplicar Monitoring
argocd app sync sky-monitoring-prod
argocd app sync sky-loki-prod
```

### Sync automático via ArgoCD
```bash
# Habilitar auto-sync em uma application
argocd app set sky-backend-prod --sync-policy automated --auto-prune --self-heal

# Verificar status
argocd app get sky-backend-prod
argocd app wait sky-backend-prod
```

---

## 🔍 Troubleshooting

### Pods não iniciam
```bash
# Verificar logs
kubectl logs <pod-name> -n prod

# Descrever pod para eventos
kubectl describe pod <pod-name> -n prod

# Verificar events do namespace
kubectl get events -n prod --sort-by='.lastTimestamp'
```

### Database connectivity
```bash
# Testar PostgreSQL
kubectl exec -it postgresql-0 -n prod -- psql -h localhost -U postgres -d ai_saas_db -c "SELECT version();"

# Testar Redis
kubectl exec -it redis-0 -n prod -- redis-cli -a $REDIS_PASSWORD ping
```

### Certificados HTTPS não emitidos
```bash
# Verificar status do Certificate
kubectl describe certificate <cert-name> -n prod

# Verificar Cert-Manager logs
kubectl logs -n cert-manager -l app.kubernetes.io/name=cert-manager

# Ver solvers ACME
kubectl get clusterissuer letsencrypt-prod -o yaml
```

### Secrets não sincronizando
```bash
# Verificar ExternalSecret status
kubectl describe externalsecret <secret-name> -n prod

# Verificar ClusterSecretStore
kubectl get clustersecretstore -o yaml

# Testar acesso ao Key Vault
az keyvault secret list --vault-name akv-sky-prod-<ID>
```

---

## 📊 Monitoring & Alertas

### Acessar Grafana
```bash
# Port-forward
kubectl port-forward svc/prometheus-grafana 3000:80 -n monitoring

# Padrão: admin / prom-operator
# URL: http://localhost:3000
```

### Ver métricas no Prometheus
```bash
# Port-forward
kubectl port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090 -n monitoring

# URL: http://localhost:9090
```

### Ver logs no Loki/Grafana
```bash
# Adicionar data source Loki em Grafana
# URL: http://loki:3100
# Depois criar dashboards com LogQL queries
```

### Alertas configurados
- ❌ HighErrorRate (>5% erros em 5min)
- ⏱️ HighLatency (p99 > 1s)
- 💥 PodCrashLooping (>5 restarts em 15min)
- 💾 HighMemoryUsage (>80%)
- ⚡ HighCPUUsage (>80%)
- 🗄️ DatabaseDown
- 🔴 RedisDown

---

## 🔧 Operações Comuns

### Escalar um deployment
```bash
# Scale Backend para 5 replicas
kubectl scale deployment -n prod sky-backend-prod-common-app --replicas=5

# Ou atualizar via ArgoCD
argocd app get sky-backend-prod
# Editar Values e sync
```

### Atualizar imagem
```bash
# Opção 1: Atualizar image tag em gitops/bootstrap/prod/backend.yaml
# Depois fazer push e ArgoCD sincroniza automaticamente

# Opção 2: Patch direto (não recomendado para produção)
kubectl set image deployment/sky-backend-prod-common-app \
  app=skyacrstaging.azurecr.io/sky-poc-backend:v1.0.0 \
  -n prod
```

### Rollback de deployment
```bash
# Ver histórico de rollout
kubectl rollout history deployment sky-backend-prod-common-app -n prod

# Fazer rollback
kubectl rollout undo deployment sky-backend-prod-common-app -n prod

# Ou via ArgoCD (recommit anterior no Git)
git revert <commit-hash>
git push
argocd app sync sky-backend-prod
```

### Restart de pods
```bash
# Deletar pod (Kubernetes recria automaticamente)
kubectl delete pod <pod-name> -n prod

# Ou restart estatefulset
kubectl rollout restart statefulset postgresql -n prod
```

---

## 🛡️ Segurança

### Verificar RBAC
```bash
# Listar role bindings
kubectl get rolebinding -n prod

# Verificar permissões
kubectl auth can-i get pods --as=system:serviceaccount:prod:backend-sa -n prod
```

### Rotação de secrets
```bash
# Secrets são rotacionados automaticamente por ExternalSecrets (1h)
# Para rotação manual no Key Vault:
az keyvault secret set --vault-name akv-sky-prod-<ID> --name jwt-secret-key --value <novo-valor>

# ExternalSecrets sincroniza automaticamente em ~1 hora
```

### Backup de Database
```bash
# Backup manual PostgreSQL
kubectl exec -it postgresql-0 -n prod -- pg_dump \
  -h localhost -U postgres ai_saas_db \
  > backup-$(date +%Y%m%d).sql

# Restaurar
kubectl exec -it postgresql-0 -n prod -- psql \
  -h localhost -U postgres ai_saas_db < backup.sql
```

---

## 🔄 CI/CD Pipeline

### GitHub Actions
```
Push para branch `main` ou `staging` 
  → GitHub Actions build image
  → Push para ACR
  → Atualiza gitops/bootstrap/prod/backend.yaml (image tag)
  → ArgoCD detecta mudança
  → Sincroniza e faz rolling update
```

### Verificar status do sync
```bash
# ArgoCD CLI
argocd app get sky-backend-prod

# Ou kubectl
kubectl get application sky-backend-prod -n argocd -o yaml
```

---

## 📈 Escalabilidade

### HPA (Horizontal Pod Autoscaler)
```bash
# Já configurado em deployments:
# - Backend: 2-10 replicas (CPU 50%)
# - Frontend: 2-10 replicas (CPU 50%)
# - AI: 0-1 replicas (custom metric)

# Ver status
kubectl get hpa -n prod

# Forçar ajuste para teste
kubectl top pods -n prod  # Ver uso atual
```

### Node autoscaling
```bash
# AKS node autoscaler configurado:
# - userapps pool: 1-3 nodes
# - aicpu pool: 0-1 nodes (spot)

# Ver node pools
az aks nodepool list --resource-group sky-aks-prod-rg --cluster-name sky-aks-prod

# Escalar manualmente se necessário
az aks nodepool scale \
  --resource-group sky-aks-prod-rg \
  --cluster-name sky-aks-prod \
  --name userapps \
  --node-count 5
```

---

## 🚨 Incidente Response

### Passos para investigar problema
```bash
# 1. Health check geral
./scripts/health-check-prod.sh

# 2. Ver logs de erro
kubectl logs -n prod --all-containers=true --since=10m | grep -i error

# 3. Verificar eventos
kubectl get events -n prod --sort-by='.lastTimestamp'

# 4. Descrever pods problemáticos
kubectl describe pod <pod-name> -n prod

# 5. Acessar métricas
# - Prometheus: localhost:9090
# - Grafana: localhost:3000
```

### Escalate
```bash
# Se pod está em CrashLoopBackOff
kubectl logs <pod-name> -n prod --previous

# Se database está down
./scripts/validate-databases-prod.sh

# Se HTTPS quebrou
./scripts/validate-https-prod.sh

# Se monitoring não está funcionando
./scripts/validate-monitoring-prod.sh
```

### Emergency procedures

**Scale down para economizar custos:**
```bash
./scripts/prod-toggle.sh off
```

**Destroy cluster (última opção):**
```bash
cd infra/aks
terraform destroy -var-file=terraform.tfvars.prod -lock=false
```

---

## 📋 Checklist Diário

- [ ] Verificar health check: `./scripts/health-check-prod.sh`
- [ ] Revisar logs de erro: `kubectl logs -n prod --since=24h | grep -i error`
- [ ] Verificar CPU/Memória: `kubectl top nodes; kubectl top pods -n prod`
- [ ] Verificar Grafana para anomalias
- [ ] Revisar alertas no AlertManager
- [ ] Backup de database (weekly)

---

## 📞 Escalation Path

| Severidade | Ação | Tempo |
|-----------|------|-------|
| 🟡 **Warning** | Monitorar, log em Jira | 30min |
| 🔴 **Critical** | Page on-call SRE | Imediato |
| ⛔ **Outage** | War room, RCA | Imediato |

---

## 📚 Referências

- [AKS Documentation](https://docs.microsoft.com/azure/aks/)
- [Cert-Manager Docs](https://cert-manager.io/docs/)
- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [Kubernetes Best Practices](https://kubernetes.io/docs/concepts/configuration/overview/)
- [SRE Book](https://sre.google/sre-book/)

---

**Última atualização**: 22 de janeiro de 2026  
**Responsável**: DevOps Team Sky
