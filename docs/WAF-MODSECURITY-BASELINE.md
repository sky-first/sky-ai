# Baseline do WAF (ModSecurity) para tuning (staging)

Este documento define as métricas/consultas que serão usadas para gerar o “baseline” do WAF e, posteriormente, escolher exceções e habilitar bloqueio com segurança.

## 1) Fontes de dados

### 1.1) Loki (eventos do WAF)

Quando os eventos do ModSecurity/CRS estiverem consultáveis no Loki, as consultas abaixo devem ser ajustadas ao formato real do log (regex do rule id/host/URI).

Namespace esperado do `ingress-nginx`:

- `ingress-nginx`

### 1.2) Prometheus (saúde do produto)

Para correlação com regressão pós-tuning, use como base as mesmas séries do painel de Golden Signals:

- `http_requests_total{namespace="$namespace"}` (taxa por serviço e status)
- `http_request_duration_seconds_bucket` (P99)

Referência (já existe no repo):

- [`gitops/charts/observability/dashboards/sre-golden-signals.json`](../gitops/charts/observability/dashboards/sre-golden-signals.json)

Exemplos de PromQL já prontos no painel:

- Tráfego (Rate): `sum by (service) (rate(http_requests_total{namespace="$namespace"}[5m]))`
- Erros (Rate % 5xx): `sum by (service) (rate(http_requests_total{status=~"5..", namespace="$namespace"}[5m])) / sum by (service) (rate(http_requests_total{namespace="$namespace"}[5m])) * 100`
- Latência (P99): `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{namespace="$namespace"}[5m])) by (le, service))`

## 2) Consultas Loki (modelos)

> Nota: como o formato exato do audit log do ModSecurity pode variar, comece por consultas “genéricas” (busca por strings) e depois refine com regexp para extrair `rule_id`, `host` e `uri`.

### 2.1) Volume total de eventos do WAF (por janela)

- Total de detecções/blocos/violations (string-base):
  - `{namespace="ingress-nginx"} |~ "ModSecurity"`
  - `count_over_time(...[5m])`

### 2.2) Ranking de Rule IDs (top N)

Quando os eventos contiverem o rule id no texto, use:

- Exemplo (fixo para um ID conhecido):
  - `count_over_time({namespace="ingress-nginx"} |~ "\"id\"\\s*:\\s*\"942100\"" [5m])`
- Exemplo (busca direta pelo ID como substring):
  - `count_over_time({namespace="ingress-nginx"} |~ "942100" [5m])`

Para “top N” de forma automatizada, idealmente:

1. extrair `rule_id` via `| regexp` (ou `| json` se for JSON),
2. agrupar com `sum by (rule_id)`.

O passo “top N automatizado” deve ser implementado assim que o payload real do audit log estiver definido.

### 2.3) Top URIs/rotas mais afetadas

Exemplos:

- `count_over_time({namespace="ingress-nginx"} |~ "\"REQUEST_URI\":\"/api\"" [5m])`
- `count_over_time({namespace="ingress-nginx"} |~ "/api/notifications/unread-count" [5m])`

## 3) Mapa de rotas críticas do produto (gate de regressão)

Para o gate do tuning (DetectionOnly -> Prevention), definir uma lista curta de rotas “não negociáveis” (5–8 endpoints), priorizadas pelo impacto para o cliente.

Critério recomendado:

- rotas de autenticação/login
- rotas de saúde (`/` ou endpoint equivalente para liveness/readiness)
- rotas de API do core do produto
- rotas que contêm payloads sensíveis (ex.: endpoints que usam IA/prompts e atualmente dependem de exceções WAF)

Após o baseline, o mesmo conjunto será usado para confirmar que não houve degradação relevante quando bloquear.

## 4) Correlação WAF x Produto (método)

Durante o período em que vocês coletam hits no DetectionOnly:

1. Calcular taxa de eventos do WAF por 5m (Loki).
2. Calcular taxa/percentual de erros 4xx e 5xx por 5m (Prometheus).
3. Calcular P99 de latência por 5m (Prometheus).
4. Comparar antes/depois da mudança de tuning (exceções e/ou ativação de modo efetivo).

Regras práticas:

- Aumento sustentado de `5xx` ou `P99` correlacionado com spike de WAF indica falso-positivo crítico ou regra ampla demais.
- Aumento de `4xx` sem impacto em `5xx` pode ser aceitável se for “bloqueio esperado” (depende do objetivo do produto).

## 5) Saída esperada do to-do `waf-3-metrics-baseline`

No fim desta fase, o time deve ter:

- um “baseline report” preenchido com:
  - Top rule ids (top N)
  - Top hosts e top URIs (ou rotas do produto)
  - correlação temporal com `4xx/5xx` e P99
- uma lista de rotas críticas (5–8) para virar o gate de regressão.
