# SUBTASK 5: Ativar Bloqueio no Staging - PLANO DE EXECUÇÃO DETALHADO

**Data**: 30 de Março de 2026  
**Status**: ⏳ PREPARANDO EXECUÇÃO  
**Objetivo**: Mudar `SecRuleEngine DetectionOnly` → `SecRuleEngine On` com validação de zero regressions

---

## VISÃO GERAL - O QUE VAI SER FEITO

### Fase 1: Preparação (Pre-Deploy)
1. **Validar baseline anterior** (SUBTASK 3-4 dados)
2. **Backup da config atual** (git tag)
3. **Preparar change set** (arquivo único a editar)
4. **Validar dependências** (nenhuma bloqueadora)

### Fase 2: Deployment
1. **Editar arquivo**: `gitops/bootstrap/staging/ingress-nginx.yaml`
   - Change: `SecRuleEngine DetectionOnly` → `SecRuleEngine On`
   - Location: linha ~32
   - Type: 1 linha apenas

2. **Commit + Push**
   - Message: "SUBTASK 5: Ativar ModSecurity bloqueio em staging"
   - Branch: `DO2025-728-devops-revisao-e-configuracao-de-firewall-waf`
   - Sync: ArgoCD detecta mudança e deploys automaticamente

3. **Validar deployment**
   - ArgoCD Application status
   - Ingress-nginx controller restart (0 downtime)
   - ConfigMap ainda montado corretamente

### Fase 3: Monitoramento (24-48h)
1. **Observar métrica de bloqueios**
   - Dashboard Grafana: Events rate (deve aumentar para "Deny" actions)
   - Logs ModSecurity: Ver `[action "deny"]` nos events

2. **Testar traffic legítimo**
   - ✅ Login flow (auth endpoints)
   - ✅ API calls (health checks, metrics)
   - ✅ IA prompts (SQL queries legítimas com Rule 942100 exceção)

3. **Validar zero regressions**
   - 39 legit requests → 0 bloqueios (do baseline)
   - 4xx/5xx rates → sem mudanças inesperadas
   - Pod uptime → sem restarts

4. **Alertar se:**
   - ❌ 403 Forbidden em endpoints legítimos
   - ❌ Spike de 5xx errors
   - ❌ Pod crash/restart loop

### Fase 4: Sign-off
1. **Documentar resultados** (SUBTASK 5 report)
2. **Preparar SUBTASK 6** (regression gate)
3. **Pronto para SUBTASK 7** (prod deployment)

---

## DETALHAMENTO: MUDANÇA DE CÓDIGO

### Arquivo a Editar
```
Repositório: sky-first/sky-poc-infra
Branch:      DO2025-728-devops-revisao-e-configuracao-de-firewall-waf
Arquivo:     gitops/bootstrap/staging/ingress-nginx.yaml
Linha:       ~32 (dentro de spec.source.helm.values.controller.config)
```

### Mudança Precisa

**ANTES**:
```yaml
controller:
  config:
    allow-snippet-annotations: "true"
    enable-modsecurity: "true"
    enable-owasp-modsecurity-crs: "true"
    modsecurity-snippet: |
      SecRuleEngine DetectionOnly        # ← DETECTA SEM BLOQUEAR
```

**DEPOIS**:
```yaml
controller:
  config:
    allow-snippet-annotations: "true"
    enable-modsecurity: "true"
    enable-owasp-modsecurity-crs: "true"
    modsecurity-snippet: |
      SecRuleEngine On                   # ← BLOQUEIA ATTACKS
```

**Resumo**:
- Apenas 1 linha muda
- Modo: `DetectionOnly` → `On`
- Efeito: Ativa bloqueio (403 Forbidden nas violations)
- Rule 942100: Já tem exceção em IA endpoints (mantém funcionando)

### Impacto Esperado

| Métrica | Antes | Depois | Motivo |
|---------|-------|--------|--------|
| WAF Mode | Audit | Block | SecRuleEngine On |
| Legit traffic (39 req) | 0 bloqueios | 0 bloqueios | Não violam nenhuma rule |
| Scanner (10.1.1.222) | Detectado | **Bloqueado** | Rules ativas bloqueiam |
| IA endpoints | Funcional | Funcional | Rule 942100 já exceção |
| HTTP 4xx/5xx | Baseline | ~Igual | Sem mudanças inesperadas |
| Pod restarts | 0 | 0 | Config change não causa crash |

---

## FASE 1: VALIDAÇÕES PRÉ-DEPLOYMENT

### Validação 1: Baseline SUBTASK 3 Confirmado

✅ **Status**: VALIDADO
```
Período:           Last 1000 logs (~2-3h)
Total events:      93
Legit GET/POST:    39 (0 bloqueios esperados ao ativar)
Scanner events:    71 (será bloqueado)
False positives:   0
Rule 942100:       0 eventos (já desabilitada em IA)
```

**Decisão**: Seguro para ativar bloqueio - legit traffic não será impactado.

### Validação 2: Rule 942100 Exceção Confirmada

✅ **Status**: VALIDADO
```
IA Endpoints (com exceção):
  ✓ backend.yaml               - SecRuleRemoveById 942100
  ✓ frontend.yaml              - SecRuleRemoveById 942100
  ✓ teamblue-backend.yaml      - SecRuleRemoveById 942100
  ✓ teamblue-frontend.yaml     - SecRuleRemoveById 942100
  ✓ values-sky-be-stg.yaml     - SecRuleRemoveById 942100
  ✓ values-sky-fe-stg.yaml     - SecRuleRemoveById 942100
  ✓ values-sky-be-teamblue-stg - SecRuleRemoveById 942100
  ✓ values-sky-fe-teamblue-stg - SecRuleRemoveById 942100

Outros Endpoints (proteção ativa):
  ✓ Health checks      - Rule 942100 ATIVA
  ✓ Metrics endpoints  - Rule 942100 ATIVA
  ✓ Auth endpoints     - Rule 942100 ATIVA
```

**Decisão**: Proteção está configurada corretamente - IA funcionará, resto protegido.

### Validação 3: Observabilidade Pronta

✅ **Status**: VALIDADO
```
Promtail:          ✓ Coletando logs do controller
Loki:              ✓ Ingestando eventos ModSecurity
Grafana:           ✓ Dashboard criado com 8 painéis
Latência:          ✓ 2-5 segundos (confirmado em SUBTASK 2)
Audit trail:       ✓ SecAuditLog /dev/stderr
```

**Decisão**: Podemos monitorar mudanças em tempo real post-deploy.

### Validação 4: Nenhum Bloqueador de Dependência

✅ **Status**: VALIDADO
```
Bloqueadores pendentes:     NENHUM
Dependências faltando:      NENHUM
Aprovações requeridas:      NENHUM
SUBTASK 1-4 status:         100% COMPLETO
```

**Decisão**: Pronto para proceder imediatamente.

---

## FASE 2: PROCEDIMENTO DE DEPLOYMENT

### Step 1: Criar Backup (Git Tag)

```bash
# Salvar snapshot da config atual (DetectionOnly)
git tag -a "subtask-5-pre-activation-$(date +%Y%m%d_%H%M%S)" \
  -m "SUBTASK 5 Pre-Activation: SecRuleEngine DetectionOnly
  
  Baseline: 93 events / 39 legit requests
  Rule 942100: Disabled in IA endpoints
  Ready to activate blocking mode"

git push origin --tags
```

**Benefício**: Fácil rollback se necessário.

### Step 2: Editar Arquivo

Arquivo: `gitops/bootstrap/staging/ingress-nginx.yaml`

**Mudança**:
```yaml
# Linha ~32
SecRuleEngine DetectionOnly  →  SecRuleEngine On
```

**Tool**: `replace_string_in_file` (1 linha, contexto simples)

### Step 3: Commit

```bash
git add gitops/bootstrap/staging/ingress-nginx.yaml
git commit -m "SUBTASK 5: Ativar ModSecurity bloqueio em staging

- Change SecRuleEngine: DetectionOnly → On
- Baseline validated: 39 legit requests, 0 expected blocks
- Rule 942100 exception active in IA endpoints
- Observability ready: Grafana dashboard + alerts
- Zero dependencies blocking deployment

Related: DO2025-728-devops-revisao-e-configuracao-de-firewall-waf"
```

### Step 4: Push + Sync

```bash
git push origin DO2025-728-devops-revisao-e-configuracao-de-firewall-waf

# ArgoCD auto-syncs (5-10 segundos)
# Ingress-nginx controller redeploys (0 downtime, rolling update)
```

### Step 5: Validar Deployment

```bash
# 1. Check ArgoCD Application
kubectl get application -n argocd ingress-nginx -o yaml | grep -A 5 "status:"

# 2. Check Controller Status
kubectl get pods -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx
# Expected: 1/1 Ready, 1 Restart Count (from deployment)

# 3. Verify Config Loaded
kubectl exec -n ingress-nginx <pod> -- \
  cat /etc/nginx/modsecurity/modsecurity.conf | grep "SecRuleEngine"
# Expected output: SecRuleEngine On

# 4. Check for Errors
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=50 | grep -i error
# Expected: 0 errors
```

---

## FASE 3: MONITORAMENTO (24-48h)

### Métrica 1: WAF Bloqueios

**Observar via Grafana**:
```
Dashboard: ModSecurity WAF - Baseline Metrics
Panel: "Total Rules Triggered (1h)" / "Critical Events"

Before:  ~0 denials (DetectionOnly mode)
After:   ~[n] denials (On mode)

Expected change:
  - Scanner (10.1.1.222): 71 events → Blocked
  - Legit traffic: 39 requests → Pass (0 blocks)
```

### Métrica 2: Action Confirmação nos Logs

```bash
# Check logs for [action "deny"]
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx \
  | grep "ModSecurity" | grep "action" | tail -20

# Expected pattern:
# ModSecurity: Audit [...] [action "deny"] ...
# ModSecurity: Audit [...] [action "log"] ...  (still logs without deny)
```

### Métrica 3: HTTP Status Distribution

```
Expected AFTER activation:
- 200 OK:         ~20-30  (legit gets, posts)
- 302 Redirect:   ~10-15  (auth redirects)
- 403 Forbidden:  ~50-70  (attacks blocked by WAF) ← NEW
- 404 Not Found:  ~10-20  (scanner probing invalid paths)
- 5xx Errors:     ~0-2    (should remain minimal)
```

### Métrica 4: Application Error Rate

```
Baseline (from SUBTASK 3):
  HTTP 4xx/5xx: 71 requests (61% of traffic)
  
Expected post-activation:
  HTTP 4xx/5xx: ~50-60 requests (similar or less)
  ↳ 403 Forbidden: WAF blocks (now explicit)
  ↳ 404 Not Found: Invalid paths (unchanged)
  
Regression indicator:
  ❌ If 4xx/5xx INCREASES significantly → False positives
  ✅ If 4xx/5xx STABLE or DECREASES → Correct operation
```

### Teste 1: IA Chat (Critical Path)

**Procedure**:
```bash
# 1. Send legitimate SQL query to IA endpoint
curl -X POST https://workspace-stg-api.skyfirstlabs.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "SELECT * FROM users WHERE id = 1"}'

# Expected: HTTP 200 OK (not 403)
# Rule 942100 exception active, query passes

# 2. Repeat with different SQL patterns
# - "SELECT ... UNION ..." 
# - "INSERT INTO ..."
# - "UPDATE ... WHERE ..."

# 3. Check logs for events
kubectl logs -n ingress-nginx | grep "ModSecurity" | grep "942100"
# Expected: 0 matches (rule disabled, no trigger)
```

### Teste 2: Auth Flow

**Procedure**:
```bash
# 1. Login attempt
curl -X POST https://workspace-stg.skyfirstlabs.com/login \
  -d "username=testuser&password=testpass"

# Expected: HTTP 302 Redirect (login page → dashboard)

# 2. Check for WAF false positives
kubectl logs -n ingress-nginx | grep "ModSecurity" | grep "login"
# Expected: 0 denials (auth flow should pass)
```

### Teste 3: Health Checks

**Procedure**:
```bash
# 1. Health endpoint
curl https://workspace-stg-api.skyfirstlabs.com/health

# Expected: HTTP 200 OK

# 2. Metrics endpoint
curl https://workspace-stg-api.skyfirstlabs.com/metrics

# Expected: HTTP 200 OK or 401 (if auth required)
```

### Teste 4: Legitimate API Calls

**Procedure**:
```bash
# 1. Get user data (no SQL, standard API)
curl https://workspace-stg-api.skyfirstlabs.com/api/users/123

# Expected: HTTP 200 OK (or 401/404 if auth/not found)

# 2. Get application data
curl https://workspace-stg-api.skyfirstlabs.com/api/apps

# Expected: HTTP 200 OK or 401
```

### Alerta: Condições de Rollback

Se qualquer uma destas ocorrer, rollback imediato:

```
❌ CONDITION 1: High false positive rate
   Indicador: 50%+ of legit requests getting 403
   Action: git revert + push

❌ CONDITION 2: Application error spike
   Indicador: 5xx errors increase >20% vs baseline
   Action: git revert + push

❌ CONDITION 3: IA prompts failing
   Indicador: Chat returning 403 on valid SQL queries
   Action: git revert + push

❌ CONDITION 4: Pod crash loop
   Indicador: Controller crashes/restarts repeatedly
   Action: git revert + push + investigate config

Rollback command:
git revert HEAD --no-edit
git push origin DO2025-728-devops-revisao-e-configuracao-de-firewall-waf
```

---

## FASE 4: SIGN-OFF E PRÓXIMOS PASSOS

### Se SUBTASK 5 Sucesso ✅

**Criteria**:
- ✅ Deployment successful (0 errors)
- ✅ 24h monitoring shows zero regressions
- ✅ IA chat working normally
- ✅ Legitimate traffic passing through
- ✅ Scanner traffic being blocked

**Actions**:
1. Create `docs/SUBTASK-5-ATIVACAO-BLOQUEIO-COMPLETA.md`
2. Document: metrics, tests, findings
3. Get user approval to proceed to SUBTASK 6
4. Prepare SUBTASK 6: Gate de Regressão

### Se SUBTASK 5 Bloqueado ❌

**Criteria**:
- ❌ False positives detected
- ❌ IA broken (Rule 942100 not working properly)
- ❌ Application errors

**Actions**:
1. Immediately rollback
2. Investigate root cause
3. Document issue in `docs/SUBTASK-5-BLOCKER-ANALYSIS.md`
4. Return to SUBTASK 4 for additional calibration
5. Retry SUBTASK 5

---

## TIMELINE & RECURSOS

### Estimativa de Tempo

| Fase | Tarefa | Tempo |
|------|--------|-------|
| 1 | Preparação + validações | 15 min |
| 2 | Deployment (edit + commit + sync) | 5 min |
| 3 | Monitoramento (24-48h) | 24-48 h |
| 4 | Sign-off + próximos passos | 30 min |
| **Total** | | **~24-48h** |

### Recursos Requeridos

```
✓ Editor (VS Code)
✓ Git client (push)
✓ kubectl (monitoring)
✓ Grafana access (dashboard)
✓ Terminal access (testing)
```

---

## DEPENDÊNCIAS VALIDADAS

### Bloqueadores: NENHUM ✅

```
✓ SUBTASK 1: Inventário         - 10/10 aceites
✓ SUBTASK 2: Observabilidade    - 8/8 aceites
✓ SUBTASK 3: Baseline & Métricas - 8/8 aceites
✓ SUBTASK 4: Calibração         - 7/7 aceites
✓ Git repository                - Operacional
✓ ArgoCD sync                   - Automático
✓ Ingress-nginx deployment      - Ativo
✓ Loki + Promtail + Grafana     - Funcionando
```

### Dependências SUBTASK 5 → SUBTASK 6

```
SUBTASK 5 Output:
  - ✅ Bloqueio ativado (SecRuleEngine On)
  - ✅ 24-48h monitoramento completo
  - ✅ Zero regressions confirmado
  - ✅ IA funcionando normalmente

Entrada SUBTASK 6:
  - ✅ Regras bloqueando corretamente
  - ✅ Legit traffic passando
  - ✅ Baseline para comparação
```

---

## CONCLUSÃO

**SUBTASK 5 está pronto para execução imediata.**

- ✅ Mudança de código: 1 linha (simples, low-risk)
- ✅ Baseline validado: 39 legit requests, 0 expected blocks
- ✅ IA exceção confirmada: Rule 942100 desabilitada
- ✅ Observabilidade ativa: Grafana + Loki pronto
- ✅ Zero bloqueadores
- ✅ Plano de monitoramento definido
- ✅ Critérios de sucesso claros
- ✅ Plano de rollback pronto

**Autorização do usuário requerida para iniciar Fase 2 (Deployment).**

---

**Assinado**: GitHub Copilot - Distinguished DevOps/SRE Engineer  
**Data**: 30 de Março de 2026  
**Status**: ✅ PRONTO PARA EXECUÇÃO
