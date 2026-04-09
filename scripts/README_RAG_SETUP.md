# Configuração do RAG - Resumo

## ✅ O que foi feito

### 1. Tabela de Embeddings
- ✅ Tabela `embeddings` criada no banco
- ⚠️ pgvector não está instalado (busca vetorial desabilitada, usando JSONB temporariamente)

### 2. Scripts Criados
- ✅ `check_embeddings.py` - Verifica status dos embeddings no banco
- ✅ `generate_embeddings.py` - Gera embeddings dos metadados de tabelas

### 3. Scripts Removidos
- ❌ `backfill_embeddings.py` - Usava modelo antigo, não funcionava
- ❌ `diagnose_flow.py` - Script temporário
- ❌ `diagnose_infrastructure.py` - Script temporário  
- ❌ `quick_fix.sh` - Script temporário
- ❌ `fix_infrastructure.sh` - Script temporário

## 📋 Próximos Passos (Para Ativar o RAG)

### ✅ Geração Automática de Embeddings

**Os embeddings são gerados automaticamente** quando você chama o endpoint `/discover`:

```bash
# Via API - Gera embeddings automaticamente por padrão
POST /connections/{connection_id}/discover?space_id={space_id}

# Isso irá:
# 1. Descobrir metadados das tabelas
# 2. Popular a tabela table_metadata
# 3. Gerar embeddings automaticamente
```

### Opções de Geração

**Opção 1: Automática (Recomendado)**
```bash
POST /connections/{connection_id}/discover?space_id={space_id}&auto_generate_embeddings=true
# Por padrão, auto_generate_embeddings=true, então não precisa especificar
```

**Opção 2: Manual (se quiser desabilitar)**
```bash
# Descobrir sem gerar embeddings
POST /connections/{connection_id}/discover?space_id={space_id}&auto_generate_embeddings=false

# Depois gerar embeddings manualmente
POST /connections/{connection_id}/generate-embeddings?space_id={space_id}
```

**Opção 3: Via Script**
```bash
python scripts/generate_embeddings.py \
  --space-id {space_id} \
  --connection-id {connection_id}
```

### Verificar
Verificar se os embeddings foram criados:

```bash
python scripts/check_embeddings.py
```

## 🔍 Status Atual

- ✅ Tabela `embeddings`: **Criada**
- ❌ Tabela `table_metadata`: **Não existe** (precisa descobrir metadados primeiro)
- ❌ Embeddings no banco: **0** (precisa gerar após descobrir metadados)
- ⚠️ pgvector: **Não instalado** (busca vetorial desabilitada)

## 🐛 Problema Identificado

O RAG não está funcionando porque:
1. Não há embeddings no banco (tabela está vazia)
2. A tabela `table_metadata` não existe (metadados não foram descobertos)

Isso explica por que o specialist está retornando `IMPOSSIBLE` na primeira tentativa - ele não tem contexto suficiente dos metadados das tabelas.

## 💡 Solução

1. **Descobrir metadados primeiro** (cria `table_metadata`)
2. **Gerar embeddings** (popula `embeddings` com contexto)
3. **RAG funcionará** (specialist terá contexto relevante)

## 📝 Notas

- O script `generate_embeddings.py` verifica automaticamente se há metadados antes de tentar gerar embeddings
- Sem pgvector, a busca será feita apenas por filtro (sem similaridade vetorial), mas ainda funcionará
- Para melhor performance, instale pgvector no PostgreSQL

