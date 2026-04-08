# 📁 Scripts - Guia de Uso

## ✅ Scripts Essenciais (Manter)

### Setup e Infraestrutura
- `create_test_data.py` - Cria dados de teste (spaces, connections, users)
- `create_table_metadata.py` - Cria tabela `table_metadata` no PostgreSQL
- `create_embeddings_table.py` - Cria tabela `embeddings` (com suporte a pgvector)
- `bootstrap_test_env.py` - Setup completo do ambiente de teste

### Testes e Desenvolvimento
- `test_interactive.py` - **Teste interativo** - Faça perguntas no terminal
- `test_suite.py` - **Suite de testes automatizados** - Para CI/CD
- `test_full_pipeline.py` - Teste completo do pipeline de IA

### Utilitários
- `list_bigquery_datasets.py` - Lista datasets disponíveis no BigQuery
- `check_datasets.py` - Verifica datasets e tabelas
- `check_pgvector.py` - **Verifica status do pgvector** (diagnóstico)

## ⚠️ Scripts Substituídos por Endpoints (Podem ser Removidos)

Estes scripts foram **substituídos pelos endpoints da API**:

- ❌ `auto_discover_tables.py` → Use `POST /connections/{id}/discover`
- ❌ `ingest_metadata_for_test.py` → Use `POST /connections/{id}/discover`
- ❌ `ingest_web_metadata.py` → Use `POST /connections/{id}/discover`

**Motivo:** Agora você usa os endpoints da API em vez de scripts diretos.

## 🔧 Scripts de Debug/Teste (Manter se necessário)

- `test_bigquery_datasource.py` - Testa conexão BigQuery
- `test_datasource_factory_bigquery.py` - Testa factory de datasources
- `test_db_connection.py` - Testa conexão PostgreSQL
- `test_openai_embeddings.py` - Testa geração de embeddings

## 📊 Scripts de Seed/Demo (Opcional)

- `seed_demo_spaces.py` - Cria espaços de demonstração
- `seed_permissions.py` - Cria permissões padrão
- `backfill_embeddings.py` - Preenche embeddings existentes

## 🗑️ Scripts Obsoletos (Podem ser Removidos)

- `force_create_table.py` - Substituído por `create_table_metadata.py`
- `debug_env.py` - Debug temporário
- `install_pgvector.py` - Instalação manual (já feito pelo DevOps)

## 📝 Recomendações

### Para Produção:
- **Remova** scripts de ingestão (substituídos por endpoints)
- **Mantenha** scripts de setup (`create_*`, `bootstrap_*`)
- **Mantenha** scripts de teste (`test_*`)

### Para Desenvolvimento:
- **Mantenha tudo** - útil para debug e testes locais

## 🚀 Uso Recomendado

### Setup Inicial (uma vez):
```bash
python3 scripts/create_test_data.py
python3 scripts/create_table_metadata.py
python3 scripts/create_embeddings_table.py
```

### Testes Locais:
```bash
# Teste interativo
python3 scripts/test_interactive.py

# Suite de testes
python3 scripts/test_suite.py
```

### Produção (via API):
```bash
# Descoberta automática (não precisa mais de scripts!)
curl -X POST "http://localhost:8000/connections/{id}/discover?space_id={space_id}"
```
