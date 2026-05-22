# Roadmap — Sky AI Proactive Intelligence

Status: ✅ feito | 🔄 em andamento | ⏳ pendente | 🗂 backlog

---

## Fundação do Agente Scan (já feito)

- ✅ 1. `full_context_agent.py` — ReAct agent com MAX_REACT_ITERATIONS=20
- ✅ 2. Two-level tools — `list_tables()` + `get_table_schema()` (evita recursion limit)
- ✅ 3. BASE system prompt universal (MEANINGFUL vs NOISE)
- ✅ 4. Brain context injection — `_fetch_brain_context_sync` (OKRs/KPIs no prompt)
- ✅ 5. Multi-connection `dispatch_map` — roteia `query_table()` para o DB certo
- ✅ 6. Merged AgentConfig para personal mode — agente vê todas as 12+ tabelas
- ✅ 7. PII filter bypass em scan mode (`is_aggregated_query=True`)
- ✅ 8. `scan_briefing.py` — 4 cenários (sem histórico/sem brain, combinações)
- ✅ 9. Topic extractor — lê `chat_history`, classifica covered/uncovered via LLM
- ✅ 10. Insight store — salva insights em `embeddings` com `type=scan_insight`
- ✅ 11. Briefing injetado no system prompt antes de cada run

---

## Fase 2 — DatasetPriorityScorer (próximo)

- ✅ 12. Salvar `tables_queried` no metadata do `scan_insight` (extend save_scan_insight)
- ✅ 13. Criar `core/agents/dataset_priority_scorer.py`:
  - Componente **staleness** (tempo desde último run por dataset)
  - Componente **volatilidade** (delta de row_count entre runs)
  - Componente **profundidade restante** (combinações analíticas ainda não vistas)
  - Componente **relevância estratégica** (placeholder estático por enquanto)
- ✅ 14. Integrar scorer em `connection_query.py` — filtra `agent_config.tables` para top-5 antes de passar ao agente
- ✅ 15. Cross-dataset run — a cada 5 runs pega 1 tabela de cada conexão e injeta no briefing instrução de buscar correlações entre fontes

---

## Fase 3 — Relevância Semântica OKR→Dataset

- ✅ 16. Gerar embeddings para `description` de cada dataset — `run_dataset_description_embeddings` em `service.py`, 1 EmbeddingRecord por tabela com `kind=dataset_description`, hookado no `/discover`
- ✅ 17. Loaders `load_okr_embeddings_for_scorer` e `load_dataset_embeddings_for_scorer` — buscam vetores do Postgres para uso no scorer
- ✅ 18. `_strategic_relevance_score` substituído por cosine similarity real — max(sim(dataset_vec, okr_vecs)); fallback para keyword quando embeddings não existem ainda
- ✅ 19. Hook em `/knowledge-graph/ingest` — quando OKR/brain doc é salvo, dispara `refresh_dataset_embeddings_for_space` como asyncio.create_task (fire-and-forget), garantindo que o caminho cosine esteja sempre pronto após mudança estratégica

---

## Fase 4 — Volatility Tracker

- ✅ 20. `save_row_count_snapshots`: lê `connection_metadata.tables[].row_count`, salva 1 EmbeddingRecord por tabela com `kind=row_count_snapshot` a cada scan run
- ✅ 21. `_volatility_score(table)` substituído por delta % real: `abs(new-old)/old`, neutro 0.5 com <2 snapshots, capped em 1.0
- ✅ 22. Tabelas de eventos com alta variação de row_count sobem automaticamente no ranking via peso 0.10 no score final

---

## Fase 5 — Scheduler (runs automáticos por hora)

- ✅ 23. Celery Beat task para disparar scan por space a cada X horas (configurável)
- ✅ 24. Endpoint para configurar frequência de scan por space (ex: hourly, daily)
- ✅ 25. Webhook/notificação quando insight gerado (backend consome e notifica usuário)
- ✅ 26. "Silent run" — se scorer não encontrar nada acima do threshold, não notifica

---

## Fase 6 — Bug fixes pendentes

- ✅ 27. Mixed dispatch multi-source bug — perguntas cruzando múltiplos DBs + OKRs/signals não passam pelo DuckDB merger (dois caminhos do LangGraph não integram)

---

## Fase 7 — Conectores novos

- ✅ 28. Conector MongoDB — Aggregation Pipeline, pymongo
- ✅ 29. Conector DynamoDB — PartiQL, boto3
- ✅ 30. Conector Elasticsearch — DSL JSON, elasticsearch-py
- ✅ 31. Completar stubs Redshift e Databricks (SQLAlchemy fallback já funciona)

---

## Backlog (validar prioridade depois)

- 🗂 32. Onboarding estratégico — agente sugere OKRs baseado nos datasets detectados quando brain está vazio
- ✅ 33. Semantic deduplication real — embedding do insight gerado vs insights anteriores (cosine > 0.85 → suprimir)
- ✅ 34. Depth tracker — registrar quais combinações (dimensão × métrica) já foram exploradas por dataset
- 🗂 35. Dashboard de cobertura — UI mostrando quais datasets foram explorados, quando, e o score atual de cada um
