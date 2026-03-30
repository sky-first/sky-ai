# Padrões para exceções do WAF (ModSecurity) — evitar drift

Este documento define uma convenção para que exceções (ex.: `SecRuleRemoveById 942100`) não fiquem “espalhadas” entre arquivos inline e arquivos de valores, reduzindo risco de inconsistência entre staging/prod e de regressões invisíveis.

## 1) Estado atual (pontos de drift)

A exceção de `942100` aparece em múltiplos lugares:
- [bootstrap staging] [`gitops/bootstrap/staging/teamblue-backend.yaml`](../gitops/bootstrap/staging/teamblue-backend.yaml)
- [bootstrap staging] [`gitops/bootstrap/staging/teamblue-frontend.yaml`](../gitops/bootstrap/staging/teamblue-frontend.yaml)
- [chart values] [`gitops/charts/common-app/values-sky-be-stg.yaml`](../gitops/charts/common-app/values-sky-be-stg.yaml)
- [chart values] [`gitops/charts/common-app/values-sky-fe-stg.yaml`](../gitops/charts/common-app/values-sky-fe-stg.yaml)
- [chart values] [`gitops/charts/common-app/values-sky-be-teamblue-stg.yaml`](../gitops/charts/common-app/values-sky-be-teamblue-stg.yaml)
- [chart values] [`gitops/charts/common-app/values-sky-fe-teamblue-stg.yaml`](../gitops/charts/common-app/values-sky-fe-teamblue-stg.yaml)
- além de outros `bootstrap/staging/*` que também embutem `modsecurity-snippet` via `values: |`.

## 2) Regra de ouro (escolha um “single source of truth”)

Escolher uma das estratégias (recomendação: Strategy A):

### Strategy A (recomendada): exceções somente via chart values
- Toda alteração de exceção deve acontecer no(s) arquivo(s) `gitops/charts/common-app/values-*.yaml`.
- As `Applications` (em `gitops/bootstrap/staging/*.yaml`) devem apenas apontar `valueFiles` e evitar repetir `ingress.annotations` inline quando a exceção já existe em values.

### Strategy B: exceções somente inline nas Applications
- Admitir que values chart não serão usados para exceções.
- Então remover exceções dos arquivos `values-*.yaml` e deixar apenas em `ingress.annotations` inline nas Applications.

> Importante: não manter “híbrido” sem uma justificativa formal e documentada.

## 3) Como validar que a convenção foi aplicada

Para cada PR/Change relacionada a exceção:
1. Atualizar o inventário:
   - [`docs/WAF-MODSECURITY-INVENTORY.md`](./WAF-MODSECURITY-INVENTORY.md)
2. Atualizar a seção “estado atual”:
   - [`docs/WAF-MODSECURITY-CALIBRATION.md`](./WAF-MODSECURITY-CALIBRATION.md)
3. Conferir que não existem múltiplas cópias da mesma exceção para o mesmo host/path sem motivo.

## 4) Change management mínimo (para não quebrar o produto)

Toda exceção deve conter, em documentação:
- `rule_id` (ex.: 942100)
- host(s) e path(s) afetados
- motivo (ex.: falso positivo em prompts da IA)
- estratégia de remoção (quando/como expira a exceção)

