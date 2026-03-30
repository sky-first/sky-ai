# Calibração do WAF (ModSecurity) — DetectionOnly -> Prevention (staging)

Este documento organiza como transformar o modo `DetectionOnly` em um bloqueio efetivo sem quebrar o produto, usando critérios de tuning e as exceções existentes.

## 1) Contexto do estado atual

- ModSecurity/CRS está habilitado no `ingress-nginx` e configurado para `SecRuleEngine DetectionOnly`.
- Há exceções aplicadas por Ingress via:
  - `nginx.ingress.kubernetes.io/modsecurity-snippet: "SecRuleRemoveById 942100"`
- Motivo conhecido (pelo próprio repo):
  - “Fix AI 403 Forbidden”: a regra `942100` está removida para prompts da IA que disparavam falso-positivo (SQL Injection).
- Referência do inventário:
  - [`docs/WAF-MODSECURITY-INVENTORY.md`](./WAF-MODSECURITY-INVENTORY.md)

## 2) Critério de decisão (o que bloquear primeiro)

Quando os eventos do WAF estiverem consultáveis (Loki), para cada rule id observada:
1. Classificar impacto provável:
   - Se bate majoritariamente com endpoints não críticos e sem correlação com aumento de `4xx/5xx` sustentado: candidato a bloqueio.
   - Se bate em endpoints críticos (login, health, rotas do core do produto) e há correlação com regressões: manter exceção ou reduzir escopo.
2. Prioridade operacional:
   - Começar bloqueando “alto sinal”:
     - regras com maior volume e alta confiança (quando disponíveis no audit log),
     - categorias que historicamente reduzem exploração (ex.: traversal, protocol anomalies, scanners).
   - Evitar bloqueios iniciais em categorias historicamente conflituosas com payload do produto (ex.: SQLi em prompts/IA).

## 3) Política inicial recomendada para vocês (baseada no que já existe)

### 3.1 Regra `942100` (SQLi vs prompts de IA)

- Manter `SecRuleRemoveById 942100` nos mesmos hosts/paths atuais até haver:
  - baseline preenchido (rule ids + endpoints),
  - correlação WAF x produto (4xx/5xx e P99),
  - confirmação no staging em `Prevention`.

### 3.2 Regras novas para exceção (quando necessário)

Quando houver falso-positivo em DetectionOnly, criar exceção com:
- escopo mínimo (preferir host + path específico),
- justificativa no documento de tuning (qual endpoint/padrão disparou, por quê),
- data e responsável.

## 4) Saída esperada (o que virar “próxima fase”)

Quando vocês preencherem o baseline (to-do `waf-3`), converter em:

1. Lista priorizada de rules/categorias para virar bloqueio na próxima alteração:
   - `rules_block_next`: top N regras candidatas a bloquear,
   - `rules_keep_detection`: regras que permanecem só em detecção.
2. Lista revisada de exceções:
   - `exceptions_current`: 942100 (mantida),
   - `exceptions_delta`: novas exceções apenas se correlacionarem com regressão.

## 5) Como validar que a calibração está correta

Após habilitar `Prevention` no staging:
- Usar o gate do to-do `waf-7` para garantir que rotas críticas funcionam.
- Acompanhar 1–2 horas de:
  - spike de `5xx` e `P99`,
  - aumento de `4xx` em rotas críticas.

