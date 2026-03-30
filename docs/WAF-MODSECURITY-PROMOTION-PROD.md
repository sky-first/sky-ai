# Promoção do WAF para prod + rollback rápido

Este documento descreve como promover a configuração de WAF do `staging` para `prod` com controle de risco e rollback claro.

## 1) Onde promover (arquivo de prod)

Revisar/aplicar no arquivo:
- [`gitops/inactive/prod/ingress-nginx.yaml`](../gitops/inactive/prod/ingress-nginx.yaml)

Pontos do `modsecurity-snippet`:
- `SecRuleEngine On` (para bloqueio efetivo)
- manter/exceções `SecRuleRemoveById 942100` conforme necessário nas Applications/values

## 2) Ordem recomendada (anti-regressão)

1. Garantir que `staging` passou no gate de regressão (`waf-7`).
2. Fazer uma única mudança consistente entre staging/prod (evitar “mix” de exceções).
3. Aplicar em prod com janela curta de monitoramento (ex.: 24–48h com atenção máxima nas primeiras horas).

## 3) Métricas e sinais para decidir rollback

Monitorar:
- 5xx rate (Prometheus)
- P99 de latência (Prometheus)
- crescimento de `4xx` em rotas críticas (para diferenciar bloqueio esperado vs quebra funcional)

Se houver:
- aumento sustentado e correlacionado de `5xx` / P99,
- degradação funcional em fluxos críticos,

então:
- rollback imediato para o estado anterior.

## 4) Rollback

- Voltar `SecRuleEngine On` -> `SecRuleEngine DetectionOnly`
- Reaplicar via GitOps

## 5) Critério de aceite (to-do `waf-8-prod-promotion-rollback`)

- `prod` fica em modo preventivo e mantém comportamento esperado,
- rollback documentado e executável em um tempo-alvo definido pelo time (ex.: 30–60 minutos).

