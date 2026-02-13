# [P0.1] Implement Non-Root Execution for All Pods

## 🎯 Objetivo

Garantir que todos os pods em staging rodem como usuário não-root **ANTES** de ativar Kyverno Enforce mode.

Esta é a **Fase 1 (P0.1)** do roadmap de maturidade operacional para elevar a nota de segurança de 5/10 → 9/10.

---

## 📋 Mudanças Implementadas

### SecurityContext Adicionado em TODOS os Pods

#### 1. **Backend (sky-be-stg)**
```yaml
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  fsGroup: 10001

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
```

#### 2. **AI Service (sky-ai-stg)**
- SecurityContext (runAsNonRoot: true)
- **Volume:** `/tmp` (5Gi) para frameworks de IA (TensorFlow, PyTorch)

#### 3. **Frontend (sky-fe-stg)**
- SecurityContext (runAsNonRoot: true)
- **Volume:** `/var/cache/nginx` (1Gi) para cache do Nginx

#### 4. **AI Worker (sky-ai-worker-stg)**
- SecurityContext (runAsNonRoot: true)
- **Volume:** `/tmp` (2Gi) para processamento temporário

#### 5. **PostgreSQL**
- SecurityContext com `runAsUser: 999` (usuário padrão do postgres)

#### 6. **Redis**
- SecurityContext com `runAsUser: 999` (usuário padrão do redis)

---

### Template Helm Atualizado

- ✅ Adicionado suporte para `extraVolumes`
- ✅ Adicionado suporte para `extraVolumeMounts`

---

## 🧪 Testes Executados (ANTES do Commit)

### ✅ Validação de Sintaxe YAML
```bash
helm template sky-be-stg ./gitops/charts/common-app -f ./gitops/charts/common-app/values-sky-be-stg.yaml
helm template sky-ai-stg ./gitops/charts/common-app -f ./gitops/charts/common-app/values-sky-ai-stg.yaml
helm template sky-fe-stg ./gitops/charts/common-app -f ./gitops/charts/common-app/values-sky-fe-stg.yaml
helm template sky-ai-worker-stg ./gitops/charts/common-app -f ./gitops/charts/common-app/values-sky-ai-worker-stg.yaml
```
**Resultado:** ✅ PASSOU - Todos os templates geraram YAML válido

---

### ✅ Validação de SecurityContext
```bash
helm template sky-fe-stg ./gitops/charts/common-app -f ./gitops/charts/common-app/values-sky-fe-stg.yaml | grep -A 10 "securityContext:"
```
**Resultado:** ✅ PASSOU - SecurityContext aplicado corretamente
```yaml
securityContext:
  fsGroup: 10001
  runAsNonRoot: true
  runAsUser: 10001
containers:
  securityContext:
    allowPrivilegeEscalation: false
    capabilities:
      drop: [ALL]
```

---

### ✅ Validação de Volumes
```bash
helm template sky-ai-stg ./gitops/charts/common-app -f ./gitops/charts/common-app/values-sky-ai-stg.yaml | grep -A 5 "volumes:"
```
**Resultado:** ✅ PASSOU - Volumes criados corretamente
```yaml
volumes:
  - emptyDir:
      sizeLimit: 5Gi
    name: tmp-volume
```

---

## 📊 Resumo de Mudanças

```
9 arquivos modificados, 639 linhas adicionadas (+)

docs/security/p0.1-validation.md                     | novo arquivo
docs/security/p0.1-visual-validation.md               | novo arquivo
gitops/charts/common-app/templates/deployment.yaml    |  8 +++
gitops/charts/common-app/values-sky-ai-stg.yaml       | 24 +++++++++
gitops/charts/common-app/values-sky-ai-worker-stg.yaml| 24 +++++++++
gitops/charts/common-app/values-sky-be-stg.yaml       | 14 ++++++
gitops/charts/common-app/values-sky-fe-stg.yaml       | 24 +++++++++
gitops/manifests/databases/postgres.yaml              | 11 +++++
gitops/manifests/databases/redis.yaml                 | 11 +++++
```

---

## ⚠️ Plano de Validação Pós-Merge

### Janela de Observação: **1 HORA**

Após merge e deploy via ArgoCD, executar:

#### 1. Validar que pods estão rodando como non-root
```bash
kubectl get pods -n staging -o json | jq -r '.items[] | "\(.metadata.name): runAsNonRoot=\(.spec.securityContext.runAsNonRoot)"'
```
**Esperado:** Todos com `runAsNonRoot=true`

---

#### 2. Verificar restart count (deve ser 0)
```bash
kubectl get pods -n staging -o json | jq '.items[] | {name:.metadata.name, restarts:.status.containerStatuses[0].restartCount}'
```
**Esperado:** `restarts: 0`

---

#### 3. Verificar erros de permissão nos logs
```bash
kubectl logs -n staging -l app.kubernetes.io/instance=sky-be-stg --tail=100 | grep -i "permission denied\|EACCES"
kubectl logs -n staging -l app.kubernetes.io/instance=sky-ai-stg --tail=100 | grep -i "permission denied\|EACCES"
kubectl logs -n staging -l app.kubernetes.io/instance=sky-fe-stg --tail=100 | grep -i "permission denied\|EACCES"
```
**Esperado:** Nenhum erro de permissão

---

#### 4. Validar latência (deve permanecer estável)
**Esperado:** Latência similar ao baseline (< 100ms P95)

---

#### 5. Validar error rate 5xx
```bash
kubectl logs -n staging -l app.kubernetes.io/instance=sky-be-stg --since=1h | grep " 5[0-9][0-9] "
```
**Esperado:** Error rate < 0.1%

---

## ✅ Critérios de Sucesso

Para considerar P0.1 **bem-sucedido**, todos os itens devem ser ✅:

- [ ] Todos os pods sobem com `runAsNonRoot: true`
- [ ] Restart count = 0 após 1 hora
- [ ] Nenhum erro de permissão nos logs
- [ ] Latência P95 < 100ms (similar ao baseline)
- [ ] Error rate 5xx < 0.1%
- [ ] Memory spike < 10% (comparado ao baseline)

---

## 🔄 Plano de Rollback (<10 minutos)

Se algo der errado:

### Opção 1: Rollback via ArgoCD (Recomendado)
```bash
argocd app history sky-be-stg -n argocd
argocd app rollback sky-be-stg <REVISION> -n argocd
```
**Tempo:** 2-3 minutos

### Opção 2: Rollback via Git
```bash
git revert 700d27b
git push origin staging
```
**Tempo:** 5 minutos

---

## 📞 Próximos Passos

### Imediato (Após Merge)
1. ✅ Merge este PR
2. ⏳ Aguardar deploy via ArgoCD (~5 minutos)
3. 🔍 Executar validação pós-deploy (comandos acima)
4. ⏱️ Observar por 1 hora
5. 📝 Documentar resultados em `docs/security/p0.1-validation.md`

### Próxima Fase (P0.2 - Após 1h de Observação)
Se tudo OK:
- Criar PR para **P0.2: Kyverno Enforce Mode**
- Ativar políticas críticas em Enforce
- Validar que pods não-conformes são bloqueados

---

## 📚 Documentação

- **Validação Completa:** `docs/security/p0.1-validation.md`
- **Validação Visual:** `docs/security/p0.1-visual-validation.md`
- **Roadmap Completo:** `implementation_roadmap.md` (artifact)

---

## 🔗 Links Relacionados

- **Branch:** `feature/p0.1-security-context-non-root`
- **Commit:** `700d27b`
- **Roadmap:** Operational Maturity Phase P0.1
- **Próximo PR:** P0.2 - Kyverno Enforce Mode

---

**Reviewer Checklist:**
- [ ] Revisar mudanças em values.yaml (securityContext)
- [ ] Validar que volumes foram adicionados corretamente
- [ ] Confirmar que postgres/redis usam user 999
- [ ] Aprovar merge
- [ ] Acompanhar deploy via ArgoCD
- [ ] Executar validação pós-deploy
