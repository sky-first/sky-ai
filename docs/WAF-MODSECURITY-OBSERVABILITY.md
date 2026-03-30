# Observabilidade do WAF (ModSecurity) no Loki

Objetivo: garantir que eventos do ModSecurity (CRS) do `ingress-nginx` fiquem visíveis no Loki/Grafana para que o tuning (DetectionOnly -> Prevention) seja baseado em dados.

## O que já está sendo preparado no código (staging)

### 1) Promtail vai coletar logs do controller

- `ingress-nginx` controller passa a ter a annotation:
  - `promtail.io/scrape: "true"`
- Arquivo:
  - [`gitops/bootstrap/staging/ingress-nginx.yaml`](../gitops/bootstrap/staging/ingress-nginx.yaml)

### 2) ModSecurity emite audit logs relevantes (tentativa via `modsecurity-snippet`)

- `modsecurity-snippet` no `ingress-nginx` inclui:
  - `SecRuleEngine DetectionOnly`
  - `SecAuditEngine RelevantOnly`
  - `SecAuditLog /dev/stderr`
  - `SecAuditLogParts ABFHZ`
- Arquivo:
  - [`gitops/bootstrap/staging/ingress-nginx.yaml`](../gitops/bootstrap/staging/ingress-nginx.yaml)

Isso reduz ruído (RelevantOnly) e evita logar request body completo (ABFHZ), mantendo a trilha com regras matchadas (H).

### 3) Limitação encontrada (importante)

Durante validação no controller:

- o `ingress-nginx` injeta apenas a primeira linha de `modsecurity-snippet` no bloco `modsecurity_rules` do `/etc/nginx/nginx.conf` (observado via `kubectl exec`).
- o audit log do ModSecurity continua sendo configurado para arquivo (ex.: `SecAuditLog /var/log/modsec_audit.log`), e os eventos não aparecem no stdout/stderr do controller apenas com essa chave.
- o promtail desta stack coleta logs de **stdout/stderr dos pods** (com filtro por `promtail.io/scrape=true`), não lê arquivos internos como `/var/log/modsec_audit.log`.

Resultado prático: para cumprir o critério de aceite “evento do WAF consultável no Loki”, precisamos de um mecanismo de **forwarding** dos logs de audit para stdout/stderr (ex.: sidecar que faz `tail -F /var/log/modsec_audit.log` e emite para console) ou uma estratégia alternativa de injeção/montagem de config do ModSecurity suportada pelo chart.

## Passo-a-passo para validar (depois de sincronizar o GitOps)

### 1) Confirmar annotation no pod real

1. Rodar:
   - `kubectl get pod -n ingress-nginx <POD_DO_CONTROLLER> -o jsonpath='{.metadata.annotations}'`
2. Verificar:
   - existe `promtail.io/scrape=true` (ou `promtail.io/scrape:"true"`)

### 2) Gerar tráfego que dispare detecções do CRS

1. Escolha um endpoint que passe pelo Ingress (ex.: host `workspace-stg.skyfirstlabs.com` e path `/api`).
2. Envie um payload que normalmente aciona regras de SQLi/Injection, por exemplo:
   - exemplo (ajuste o endpoint real): `/api/search?q=' OR '1'='1`

> Observação: o exato payload necessário varia por regra/endpoint. Como há exceção de `942100` (via `SecRuleRemoveById 942100`) em alguns hosts, prefira endpoints/hosts que NÃO estejam cobertos por essa exceção para garantir hits.

### 3) Verificar no log do controller (stdout/stderr do NGINX)

1. Rodar:
   - `kubectl logs -n ingress-nginx <DEPLOYMENT_DO_CONTROLLER> --tail=200 | <filtro por 942100> (ou por "ModSecurity")`
2. Critério:
   - deve aparecer a entrada de audit do ModSecurity com o rule id (ex.: `942100`) e metadados de host/URI.

### 4) Consultar no Loki/Grafana (LogQL)

No Grafana Explore (datasource Loki), use primeiro a regra id:

- Query 1 (rule id):
  - `{namespace="ingress-nginx"} |~ "942100"`

Se não aparecer `942100`, busque o evento de audit:

- Query 2 (audit/modsecurity):
  - `{namespace="ingress-nginx"} |~ "SecRule" or {namespace="ingress-nginx"} |~ "ModSecurity"`

Depois, confirme dentro do evento:

- o `host` (ou header Host)
- o `request line`/`URI` (ou equivalente)
- o rule id (ID de regra no trailer)

## Critério de Aceite (para o to-do `waf-2-observability`)

- Conseguir consultar no Loki/Grafana pelo menos **1 evento** de ModSecurity do `ingress-nginx` em staging.
- O evento precisa incluir de forma rastreável:
  - `rule id` (ao menos um id de regra)
  - `host` e `URI` (ou equivalente no audit log)
