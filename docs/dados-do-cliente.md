# Dados do cliente: o que o sky-ai guarda e o que não guarda

**Princípio:** nunca guardamos linhas do cliente. O SQL é gerado a partir dos metadados e corre no servidor do cliente. Só guardamos o que a plataforma gera; o que é sensível vai cifrado.

Em vigor desde 13/10/2026. Origem: auditoria de 13/10 (achados A1, A2, A3, A10, A11 e A12).

## Não guardamos

| O quê | Onde estava | Agora |
|---|---|---|
| Linhas do resultado (`data_sample`, 15 linhas) | `semantic_cache.response_json` | Grava-se a resposta, o SQL e os metadados, com `data_sample=[]` e a marca `rows_omitted`. Num acerto que precisa de linhas, o SQL guardado volta a correr na fonte do cliente. Se falhar, o acerto é descartado. Ver `core/privacidade/cache_semantico.py` |
| Estado do grafo LangGraph (até 10.000 linhas) | Tabelas `checkpoints*` na base da **plataforma** | O grafo é compilado sem checkpointer e o estado só existe na memória do pedido. A continuidade da conversa vem do `chat_history` |
| `answer` e `data_sample` de cada pedido | `pipeline_jobs.result` | O router `/pipeline` foi removido. Nenhum cliente o chamava |
| Valores das colunas, início das respostas, DSN | Logs (stdout) | O `log_event` limpa todos os eventos: os segredos saem, os dados passam a contar só o tamanho e o SQL perde os literais `'…'`. Ver `core/privacidade/registo.py` |
| Linhas devolvidas pela ferramenta `query_table` (scan) | Langfuse, se ligado | A máscara substitui-as por `[linhas do cliente omitidas]`. Um SDK sem `mask` não liga |

## Guardamos (gerado pela plataforma)

- **Cache semântica** (`semantic_cache`): pergunta, embedding, resposta, SQL e metadados, durante **30 dias**. Depois disso nunca é servida e é apagada.
- **Conversa** (`chat_history`): texto da resposta e SQL. A resposta pode citar números do cliente.
- **Auditoria** (`query_audit_log`): pergunta, SQL, contagens e `answer_preview`.
- **Metadados** (`table_metadata`, `embeddings`): esquema, tipos, comentários da base, MIN/MAX de datas e contagens de linhas. Sem valores das colunas.
- **Em memória, efémero:** valores distintos para as perguntas, no Redis durante 30 min (`core/sql/valores_de_coluna.py`), e o DuckDB do merger (`:memory:`).

Por fazer (P2): cifra ao nível da aplicação, por cliente, de `chat_history`, `query_audit_log` e dos insights, com prazos de retenção.

## Limpeza do que já estava guardado

`scripts/limpar_dados_do_cliente.py` corre na plataforma e em cada base de cliente, via `tenant_connection_manager`. É idempotente:

```
python scripts/limpar_dados_do_cliente.py           # dry-run: só conta
python scripts/limpar_dados_do_cliente.py --apply
```

O script faz o seguinte:

- tira o `data_sample` da cache e apaga as linhas com mais de 30 dias;
- esvazia `pipeline_jobs.result`;
- apaga as tabelas `checkpoint*`;
- tira «Possible values:» de `table_metadata`, `embeddings` e `context_documents` e recalcula o vector.

Corre-se **depois** do `scripts/limpar_valores_das_colunas.py` do sky-backend.
