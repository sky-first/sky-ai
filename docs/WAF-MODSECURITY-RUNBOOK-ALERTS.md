# Runbook e alertas operacionais — WAF/ModSecurity

Este runbook orienta operações durante tuning/ativação do WAF no AKS.

## 1) Verificar status do WAF (modo atual)

### 1.1) Verificar pelo ConfigMap do controller

1. Rodar:
   - `kubectl get configmap ingress-nginx-controller -n ingress-nginx -o jsonpath='{.data.modsecurity-snippet}'`
2. Esperado:
   - contém `SecRuleEngine DetectionOnly` (modo tuning) ou `SecRuleEngine On` (modo preventivo)

### 1.2) Verificar no `nginx.conf` (evidência direta)

1. Rodar:
   - `kubectl exec -n ingress-nginx <POD_DO_CONTROLLER> -- sh -c "awk '/modsecurity_rules/{flag=1} flag && /SecRuleEngine/{print; exit}' /etc/nginx/nginx.conf"`

## 2) Identificar regras (rule ids) e rotas impactadas

### 2.1) Loki (LogQL) — templates

Comece por rule id:
- `{namespace="ingress-nginx"} |~ "942100"`

Depois refine por host/URI conforme o formato real do log:
- `{namespace="ingress-nginx"} |~ "/api/notifications/unread-count"`

Se estiver consultável com regexp, extrair e agrupar (estratégia recomendada):
- 1) `| regexp` para obter `rule_id`, `host`, `uri`
- 2) `sum by (rule_id)` e `sum by (uri)` com `count_over_time`

### 2.2) Correlação com o produto (Prometheus)

Usar Golden Signals como referência:
- 5xx rate: `http_requests_total{status=~"5.."}`
- 4xx rate: `http_requests_total{status=~"4.."}`
- P99 latency: `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))`

Regra prática:
- Se WAF bloquear e aumentar `4xx` mas `5xx`/P99 não sobe: geralmente é bloqueio esperado.
- Se `5xx`/P99 sobe correlacionado: regressão/padrão amplo — rollback ou exceção mais específica.

## 3) Como aplicar exceções de forma segura

Exceções atuais no repo:
- `SecRuleRemoveById 942100` via Ingress annotation `nginx.ingress.kubernetes.io/modsecurity-snippet`.

Procedimento:
1. Escolher host/paths exatos onde a exceção é necessária (reduzir escopo).
2. Atualizar no(s) arquivo(s) responsáveis pela rota:
   - `gitops/bootstrap/staging/*.yaml` (inline) e/ou
   - `gitops/charts/common-app/values-*.yaml` (values do chart)
3. Atualizar documentação:
   - [`docs/WAF-MODSECURITY-INVENTORY.md`](./WAF-MODSECURITY-INVENTORY.md)
4. Reaplicar via GitOps.

Rollback:
- remover a exceção (se aplicável) ou voltar para o estado anterior de `modsecurity-snippet`.

## 4) Alertas recomendados

### 4.1) Métricas (Prometheus)

1. Spike de `5xx` por namespace/serviço:
   - disparar se a taxa de `status=5..` subir acima do baseline por 5–10 min
2. Spike de P99:
   - disparar se P99 exceder threshold por janela curta

### 4.2) Logs (Loki)

1. Spike de eventos do WAF:
   - `count_over_time({namespace="ingress-nginx"} |~ "ModSecurity" [5m])` subir acima do normal
2. Spike de uma regra específica:
   - `count_over_time({namespace="ingress-nginx"} |~ "942100" [5m])` (se for a regra mais sensível)

> Observação: o exato texto do log e o melhor regex dependem do formato real do audit log no Loki. Ajustar após a primeira janela com eventos.

## 5) Critério de aceite (to-do `waf-9-runbook-alerts`)

- Runbook publicado (este arquivo) com passos testáveis.
- Alertas descritos com queries/campos necessários para implementar no seu sistema de alertas (Prometheus/Loki).

