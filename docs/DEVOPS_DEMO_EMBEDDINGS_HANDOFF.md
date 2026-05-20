# DevOps Handoff — Demo Embeddings Compartilhados (PR #210)

**Data:** 2026-05-20  
**PR:** https://github.com/sky-first/sky-ai/pull/210  
**Impacto:** staging + produção (demo)  
**Urgência:** necessário antes de qualquer novo cadastro demo

---

## Contexto rápido

O PR #210 corrige um problema estrutural: cada novo usuário demo gerava
embeddings próprios para as 5 conexões NovaTech (Finance, Sales, Marketing,
Product Usage, Web Analytics). Com 1000 usuários isso seria 1000 cópias
idênticas no banco + 1000 chamadas desnecessárias à API de embeddings.

Após o merge, o sky-ai só gera os embeddings uma vez (no primeiro usuário
demo) e todos os seguintes reutilizam as mesmas rows. **Mas o código só
ativa esse comportamento se a env var abaixo estiver configurada.**

---

## Passo 1 — Adicionar env var no k8s secret do sky-ai

O sky-ai precisa saber quais connection IDs são demo. Os IDs são
**diferentes por ambiente** — cada banco gera seus próprios UUIDs quando
as conexões NovaTech são criadas.

> ⚠️ **Não use os IDs abaixo** — eles são do ambiente local de
> desenvolvimento e não existem no banco de staging nem de produção.

**A fonte correta para cada ambiente é o próprio `backend.yaml`:**

| Ambiente | De onde copiar |
|---|---|
| Staging | `DEMO_DATASET_CONNECTION_IDS` do `stg-backend.yaml` (ou secret k8s do sky-poc-backend staging) |
| Produção | `DEMO_DATASET_CONNECTION_IDS` do `prd-backend.yaml` (ou secret k8s do sky-poc-backend prod) |

Adicionar a variável no secret do **sky-ai** de cada ambiente com o valor
correspondente do backend daquele mesmo ambiente.

Como adicionar (AWS Secrets Manager via kubectl):
```bash
# Editar o secret existente do sky-ai
kubectl edit secret sky-ai-env -n <namespace>

# Ou via AWS Console: Secrets Manager → sky-ai-staging → editar e adicionar a chave
```

---

## Passo 2 — Deploy da nova imagem do sky-ai

Após merge do PR #210, buildar e deployar a nova imagem normalmente pelo
pipeline CI/CD existente. Confirmar que o pod subiu com a env var:

```bash
kubectl exec -it <pod-sky-ai> -n <namespace> -- \
  python3 -c "from config.settings import settings; print(settings.demo_dataset_connection_ids)"
# Deve imprimir os 5 UUIDs separados por vírgula
```

---

## Passo 3 — Seed inicial dos embeddings compartilhados

> **Fazer apenas uma vez, após o deploy.** Se pular este passo, o primeiro
> usuário demo que entrar fará o seed automaticamente, mas com latência alta
> (~30–60s). Recomenda-se rodar manualmente para garantir a experiência.

Chamar o endpoint de setup-rag para cada uma das 5 conexões demo,
passando `space_id` como `null` para forçar o armazenamento global:

```bash
BASE_URL="https://sky-stg-ai.skyfirstlabs.com"   # ajustar para prod quando for

# ⚠️ Substituir pelos IDs reais do ambiente (ver Passo 1)
# Fonte: DEMO_DATASET_CONNECTION_IDS no secret/yaml do sky-poc-backend deste ambiente
CONNECTION_IDS=(
  "<id-finance>"
  "<id-web-analytics>"
  "<id-product-usage>"
  "<id-sales>"
  "<id-marketing>"
)

for conn_id in "${CONNECTION_IDS[@]}"; do
  echo "Seeding connection $conn_id ..."
  curl -s -X POST "$BASE_URL/admin/setup-rag" \
    -H "Content-Type: application/json" \
    -d "{\"space_id\": null, \"connection_id\": \"$conn_id\"}" | python3 -m json.tool
  echo ""
done
```

Resposta esperada por conexão:
```json
{
  "success": true,
  "embeddings_created": 42,
  "message": "RAG setup complete! Created 42 embeddings."
}
```

Se retornar `"embeddings_created": 0` numa segunda rodada, está correto —
significa que o seed já existia e foi pulado (idempotente).

---

## Validação pós-deploy

Confirmar no banco que os embeddings estão com `space_id = NULL`:

```sql
SELECT
  COALESCE(e.space_id::text, 'NULL') AS space_id,
  COUNT(*) AS embeddings,
  COUNT(DISTINCT tm.data_connection_id) AS connections
FROM embeddings e
JOIN table_metadata tm ON tm.id = e.table_metadata_id
WHERE e.space_id IS NULL
GROUP BY e.space_id;
```

Resultado esperado: ~200–300 embeddings com `space_id = NULL` cobrindo
as 5 conexões demo.

---

## Ordem de execução resumida

| # | Ação | Ambiente |
|---|------|----------|
| 1 | Mergear PR #210 | — |
| 2 | Adicionar `DEMO_DATASET_CONNECTION_IDS` no k8s secret do sky-ai | staging e prod |
| 3 | Deploy da nova imagem sky-ai | staging primeiro, depois prod |
| 4 | Rodar script de seed inicial (Passo 3 acima) | staging primeiro, depois prod |
| 5 | Validar com a query SQL acima | staging |
| 6 | Testar as 20 perguntas demo no chat | staging |

---

## Em caso de problema

Se o seed falhar com erro de FK ou de dimensão de vetor, verificar:

1. Se a migration 005 rodou (`alembic_version` = `005_fix_embedding_dims_and_cache`)
2. Se as colunas `embedding` estão em `vector(1024)` (não `vector(768)`)
3. Se a env var `DEMO_DATASET_CONNECTION_IDS` está presente no pod

Dúvidas: chamar @kaiquemendonca1 no Slack.
