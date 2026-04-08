# 📋 Spec Técnica — Relacionamentos entre Tabelas (Para Fullstack)

> **Data:** 2026-03-03  
> **Contexto:** Feature de relacionamentos entre tabelas documentados pelo cliente.  
> **O AI Engine (`sky-poc-ai`) já está implementado.** Este documento descreve o que o Backend e o Frontend precisam fazer.

---

## Visão Geral

O cliente pode documentar que `vendas.cli_id` se relaciona com `clientes.id` via `LEFT JOIN`.  
A IA consome isso e gera JOINs corretos automaticamente, sem adivinhar por heurística.

**Fluxo:**
```
Frontend (UI) → Backend (persistência) → AI Engine (consumo no prompt)
```

---

## 1. BACKEND (`sky-poc-backend`)

### 1.1 Migração de Banco de Dados

A tabela `connection_metadata` precisa de uma nova coluna para armazenar os relacionamentos:

```sql
-- Migration: adicionar coluna 'relationships' em connection_metadata
ALTER TABLE connection_metadata
ADD COLUMN IF NOT EXISTS relationships JSONB DEFAULT '[]'::jsonb;

-- Índice opcional para performance
CREATE INDEX IF NOT EXISTS idx_connection_metadata_conn_id
ON connection_metadata (connection_id);
```

> **IMPORTANTE:** O AI Engine lê essa coluna com:
> ```sql
> SELECT relationships FROM connection_metadata
> WHERE connection_id = CAST(:cid AS uuid) LIMIT 1
> ```
> A coluna **deve** se chamar exatamente `relationships` e ser `JSONB` (ou `JSON`).

---

### 1.2 Schema do JSON de Relacionamentos

Cada item da lista `relationships` deve seguir este formato:

```json
[
  {
    "id": "uuid-v4-gerado-no-frontend",
    "from_table": "vendas",
    "from_column": "cli_id",
    "to_table": "clientes",
    "to_column": "id",
    "join_type": "LEFT",
    "label": "Venda pertence ao Cliente",
    "confidence": "explicit"
  },
  {
    "id": "uuid-v4-gerado-no-frontend",
    "from_table": "vendas",
    "from_column": "prod_id",
    "to_table": "produtos",
    "to_column": "codigo",
    "join_type": "INNER",
    "label": null,
    "confidence": "explicit"
  }
]
```

**Campos obrigatórios:**
| Campo | Tipo | Descrição |
|---|---|---|
| `id` | `string (UUID)` | Identificador único do relacionamento |
| `from_table` | `string` | Nome lógico da tabela origem |
| `from_column` | `string` | Nome da coluna FK na tabela origem |
| `to_table` | `string` | Nome lógico da tabela destino |
| `to_column` | `string` | Nome da coluna PK na tabela destino |
| `join_type` | `string` | Um de: `INNER`, `LEFT`, `RIGHT`, `FULL` |

**Campos opcionais:**
| Campo | Tipo | Descrição |
|---|---|---|
| `label` | `string \| null` | Descrição em linguagem natural |
| `confidence` | `string` | Sempre `"explicit"` para os salvos pelo cliente |

> **Nome lógico das tabelas:** O AI Engine usa `logical_name` (normalmente o nome simples sem schema). Para descobrir o `logical_name` de uma tabela, consultar `connection_metadata.tables[*].logical_name` ou `connection_metadata.tables[*].name`.

---

### 1.3 Pydantic Schemas (Back-end)

Criar em `src/schemas/connection.py`:

```python
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid

class TableRelationshipSchema(BaseModel):
    """Relacionamento entre tabelas documentado pelo cliente."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_table: str = Field(..., description="Tabela origem (logical_name)")
    from_column: str = Field(..., description="Coluna FK")
    to_table: str = Field(..., description="Tabela destino (logical_name)")
    to_column: str = Field(..., description="Coluna PK destino")
    join_type: str = Field(
        "INNER",
        description="Tipo de JOIN: INNER | LEFT | RIGHT | FULL"
    )
    label: Optional[str] = Field(None, description="Descrição legível")
    confidence: str = Field("explicit", description="Sempre 'explicit' para definidos pelo cliente")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "from_table": "vendas",
                "from_column": "cli_id",
                "to_table": "clientes",
                "to_column": "id",
                "join_type": "LEFT",
                "label": "Venda pertence ao Cliente"
            }
        }


class ConnectionRelationshipsUpdate(BaseModel):
    """Payload para salvar/substituir todos os relacionamentos de uma conexão."""
    relationships: List[TableRelationshipSchema]


class ConnectionRelationshipsResponse(BaseModel):
    """Resposta da listagem de relacionamentos."""
    connection_id: str
    relationships: List[TableRelationshipSchema]
    total: int
```

---

### 1.4 Endpoints da API

Adicionar em `src/api/v1/connections.py`:

#### `GET /api/v1/connections/{connection_id}/relationships`

Retorna os relacionamentos salvos para uma conexão.

**Response `200`:**
```json
{
  "connection_id": "uuid-da-conexao",
  "relationships": [ ...lista de TableRelationshipSchema... ],
  "total": 2
}
```

**Response `404`:** Conexão não encontrada.

---

#### `PUT /api/v1/connections/{connection_id}/relationships`

Salva/substitui completamente a lista de relacionamentos de uma conexão.

**Body:**
```json
{
  "relationships": [
    {
      "id": "uuid-gerado-no-frontend",
      "from_table": "vendas",
      "from_column": "cli_id",
      "to_table": "clientes",
      "to_column": "id",
      "join_type": "LEFT",
      "label": "Venda pertence ao Cliente"
    }
  ]
}
```

**Response `200`:**
```json
{
  "connection_id": "uuid-da-conexao",
  "relationships": [ ...lista salva... ],
  "total": 1
}
```

**Permissão:** Apenas usuários com `manageConnections` podem editar.

---

### 1.5 Lógica do Service (`connection_service.py`)

```python
# Leitura
async def get_relationships(self, connection_id: str, current_user) -> List[dict]:
    metadata = await self.metadata_repo.get_by_connection_id(connection_id)
    if not metadata:
        return []
    # Ler campo relationships do record
    raw = getattr(metadata, "relationships", None) or []
    return raw if isinstance(raw, list) else []

# Escrita (substitui lista completa)
async def save_relationships(
    self,
    connection_id: str,
    current_user,
    relationships: List[dict]
) -> List[dict]:
    metadata = await self.metadata_repo.get_by_connection_id(connection_id)
    if not metadata:
        raise NotFoundException("ConnectionMetadata not found")
    # Setar campo relationships e salvar
    metadata.relationships = relationships
    await self.metadata_repo.save(metadata)
    return relationships
```

> **Nota:** Verificar como o `metadata_repo` expõe o campo. Se o modelo SQLAlchemy de `ConnectionMetadata` não tiver a coluna `relationships`, ela precisa ser adicionada ao model após a migration.

---

## 2. FRONTEND (`sky-poc-frontend`)

### 2.1 Localização da UI

A nova interface deve estar na **aba de configuração da conexão existente**, como uma nova sub-seção/tab chamada **"Table Relationships"** (ou "Relacionamentos") ao lado das abas de Tables/Schema.

---

### 2.2 Calls de API necessárias

```typescript
// Listar relacionamentos salvos ao abrir a aba
GET /api/v1/connections/{connectionId}/relationships

// Listar tabelas para popular os dropdowns (já existe)
GET /api/v1/connections/{connectionId}/tables

// Salvar lista completa ao clicar em "Save"
PUT /api/v1/connections/{connectionId}/relationships
Body: { relationships: TableRelationship[] }
```

---

### 2.3 Componente — Interface de Relacionamentos

#### Formulário de novo relacionamento
```
[Dropdown: From Table] . [Dropdown: From Column]
         ↕  join type  ↕
[Dropdown: To Table]   . [Dropdown: To Column]

[Select: JOIN Type] → INNER JOIN | LEFT JOIN | RIGHT JOIN | FULL JOIN
[Input: Description (opcional)]

[+ Add Relationship]
```

#### Lista de relacionamentos existentes
```
┌─────────────────────────────────────────────────────────┐
│ vendas.cli_id ─LEFT JOIN─▶ clientes.id                  │
│ "Venda pertence ao Cliente"                    [🗑 Remove]│
├─────────────────────────────────────────────────────────┤
│ vendas.prod_id ─INNER JOIN─▶ produtos.codigo            │
│                                                [🗑 Remove]│
└─────────────────────────────────────────────────────────┘

[Save Relationships]
```

---

### 2.4 Lógica de UX

1. **Ao selecionar "From Table":** buscar colunas de `tables.find(t => t.name === fromTable).columns` e popular "From Column".
2. **Ao selecionar "To Table":** mesmo para "To Column".
3. **Validação antes de adicionar:**
   - `from_table !== to_table`
   - Todos os campos obrigatórios preenchidos
   - Não duplicar mesma combinação `(from_table, from_column, to_table, to_column)`
4. **Geração de ID:** `crypto.randomUUID()` no frontend ao criar o relacionamento.
5. **Salvar:** chamar `PUT /relationships` com a lista completa (não incremental — replace-all).
6. **Feedback:** Toast de sucesso/erro após save.

---

### 2.5 TypeScript Types

```typescript
export type JoinType = "INNER" | "LEFT" | "RIGHT" | "FULL";

export interface TableRelationship {
  id: string;
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  join_type: JoinType;
  label?: string;
  confidence: "explicit" | "inferred";
}

export interface ConnectionRelationshipsResponse {
  connection_id: string;
  relationships: TableRelationship[];
  total: number;
}

export interface ConnectionRelationshipsUpdate {
  relationships: TableRelationship[];
}
```

---

## 3. Critérios de Aceite para Fullstack

| Item | Critério |
|---|---|
| Migration | Coluna `relationships JSONB` existe em `connection_metadata` |
| GET endpoint | Retorna `[]` para conexão sem relacionamentos, lista correta se houver |
| PUT endpoint | Substitui lista completa, retorna a lista salva |
| Permissão | Apenas `manageConnections` pode fazer PUT |
| Frontend | Dropdowns de tabela e coluna populados corretamente |
| Frontend | Validação impede relacionamento com mesma tabela nos dois lados |
| Frontend | IDs gerados no frontend via `crypto.randomUUID()` |
| Frontend | Save usa `PUT` com lista completa |

---

## 4. O Que o AI Engine Já Faz (Não Precisa Fazer no Fullstack)

- ✅ Ler o campo `relationships` da `connection_metadata`
- ✅ Filtrar por permissão de acesso às tabelas
- ✅ Usar `join_type` correto (LEFT/INNER/RIGHT/FULL) nos JOINs gerados
- ✅ Priorizar relacionamentos `explicit` sobre os inferidos por heurística
- ✅ Exibir os JOINs documentados no prompt de forma destacada

---

## 5. Contato

Dúvidas sobre o contrato de dados? Ver também:
- `sky-poc-ai/docs/api_data_contract.md` — contratos gerais de API
- Conversar com o responsável pelo AI Engine
