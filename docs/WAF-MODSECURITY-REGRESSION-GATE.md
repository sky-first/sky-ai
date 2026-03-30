# Gate de regressão pós-ativação (DetectionOnly -> Prevention)

Este gate é usado após habilitar bloqueio efetivo no `staging` para garantir que o produto continua funcionando nas rotas críticas.

## 1) Rotas críticas (sugestão inicial)

Baseado no que aparece nos manifests do repo (hosts e paths de ingress):
- Frontend:
  - `GET /` (host workspace-stg.skyfirstlabs.com ou teamblue.skyfirstlabs.com conforme ambiente)
  - `GET /login` (fluxo de autenticação)
  - `GET /dashboard`
- Backend / API:
  - `GET /` (health liveness/readiness no backend usa `/`)
  - `GET /api` e `GET /api/<endpoint>` (rotas core)
  - `POST/PUT /api/...` (quando existir payloads)

Para endpoints sensíveis ao falso-positivo (IA/prompts):
- validar fluxos que atualmente dependem da exceção `942100` (AI 403 Forbidden).

## 2) Checklist de execução (antes/depois)

1. Defina um “baseline” de referência (1 janela curta antes da mudança):
   - `status_codes` de 4xx/5xx
   - latência P99
2. Após habilitar `Prevention`:
   - executar os checks abaixo em sequência (para os hosts do staging)
3. Critério de sucesso:
   - não deve haver aumento sustentado de `5xx`/timeouts
   - endpoints de login e health devem continuar respondendo

## 3) Checks funcionais (mínimos)

Para cada host de staging (ex.: `workspace-stg.skyfirstlabs.com` e `teamblue.skyfirstlabs.com`):
1. Health do frontend:
   - `GET /` -> `2xx/3xx esperado`
2. Saúde do backend:
   - `GET /` -> `2xx` (ou o comportamento esperado do app)
3. Health da API:
   - `GET /api` e pelo menos 1 endpoint conhecido do core (definir no baseline)
4. Flows com payload sensível:
   - repetir um fluxo que antes exigia exceção (IA/prompts) e confirmar que não voltou `403`

## 4) Critério de aceite (to-do `waf-7-regression-gate`)

Todos os checks passam e:
- indicadores de erro do produto não têm aumento relevante sustentado durante a janela definida (recomendação: 1–2 horas após a mudança),
- caso exista aumento de `4xx`, validar se é “bloqueio esperado” (e não quebra funcional do core).

