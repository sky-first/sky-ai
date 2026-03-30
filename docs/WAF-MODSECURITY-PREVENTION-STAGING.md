# Ativação de WAF efetivo (Prevention) no staging

Este documento descreve como habilitar bloqueio efetivo do ModSecurity (saindo de `DetectionOnly`) no `staging`, mantendo uma rota clara de rollback e um gate mínimo de regressão.

## 1) Mudança de configuração (o que alterar)

Arquivo (GitOps):
- [`gitops/bootstrap/staging/ingress-nginx.yaml`](../gitops/bootstrap/staging/ingress-nginx.yaml)

Campo:
- `controller.config.modsecurity-snippet`

Requisito:
- Garantir que a primeira diretiva útil comece com:
  - `SecRuleEngine On` (ou equivalente que ative prevenção)

Observação importante (aprendizado do tuning):
- No `ingress-nginx`, a chave `modsecurity-snippet` aparentemente injeta apenas o trecho de `SecRuleEngine` no `nginx.conf`.
- Portanto, o bloqueio efetivo depende principalmente de trocar `SecRuleEngine DetectionOnly` por `SecRuleEngine On`.

## 2) Preservar exceções existentes (para não quebrar o produto)

Não remover por “curiosidade” a exceção atual enquanto não houver baseline/correlação:
- `SecRuleRemoveById 942100`
- Referência do inventário:
  - [`docs/WAF-MODSECURITY-INVENTORY.md`](./WAF-MODSECURITY-INVENTORY.md)

## 3) Rollout controlado (staging)

1. Aplicar a mudança via GitOps/ArgoCD.
2. Acompanhar (1–2 horas):
   - taxa de `4xx` e `5xx` (Prometheus)
   - P99 de latência (Prometheus)
   - erros funcionais percebidos (gate do produto)
3. Se houver regressão forte:
   - rollback imediato voltando `SecRuleEngine` para `DetectionOnly`

## 4) Rollback (rollback seguro)

- Voltar `SecRuleEngine On` -> `SecRuleEngine DetectionOnly` no mesmo arquivo.
- Reaplicar via GitOps.

Critério prático:
- se `5xx` e/ou `P99` aumentarem de forma sustentada e correlacionada com WAF, reverter.

## 5) Critério de Aceite (to-do `waf-6-enable-prevention-staging`)

Para marcar como “feito”:
- requests de teste que antes eram apenas detectadas devem resultar em bloqueio (tipicamente `403` ou `4xx`, dependendo de como o produto/NGINX responde),
- as detecções/bloqueios devem ficar evidentes (em Loki se os logs estiverem consultáveis; caso contrário, evidência via logs do controller e métricas de erro).
- não deve haver regressão relevante nas rotas críticas definidas no baseline.

