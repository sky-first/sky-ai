# Guia de Integração - IA com Backend do Produto

Este guia explica como integrar a IA de SQL com seu backend do produto.

## 📋 Visão Geral

A IA já está preparada para integração automática. Quando você criar uma conexão BigQuery, o sistema pode:
1. **Descobrir automaticamente** todas as tabelas e colunas
2. **Responder perguntas** em linguagem natural usando essas tabelas

## 🚀 Opções de Integração

### Opção 1: Descoberta Automática na Criação (Recomendado)

Quando criar uma conexão no seu backend, chame automaticamente o endpoint de descoberta:

```python
# No seu backend, após criar a conexão:
import httpx

# 1. Criar conexão (seu código atual)
connection = create_connection(...)

# 2. Descobrir tabelas automaticamente
response = httpx.post(
    f"{IA_API_URL}/connections/{connection.id}/discover",
    params={"space_id": connection.space_id},
    timeout=60.0  # Pode demorar alguns segundos
)

if response.status_code == 200:
    result = response.json()
    print(f"✅ {result['tables_discovered']} tabelas descobertas")
    print(f"✅ {result['metadata_rows_inserted']} colunas catalogadas")
```

### Opção 2: Descoberta em Background

Para não bloquear a criação da conexão:

```python
# Criar conexão
connection = create_connection(...)

# Iniciar descoberta em background
httpx.post(
    f"{IA_API_URL}/connections/{connection.id}/discover",
    params={
        "space_id": connection.space_id,
        "run_in_background": "true"
    }
)
# Retorna imediatamente, executa em background
```

### Opção 3: Descoberta Manual (Via UI)

Permitir que o usuário clique em "Descobrir Tabelas" no frontend:

```javascript
// No seu frontend
async function discoverTables(connectionId, spaceId) {
  const response = await fetch(
    `${IA_API_URL}/connections/${connectionId}/discover?space_id=${spaceId}`,
    { method: 'POST' }
  );
  return response.json();
}
```

## 🔌 Endpoints Disponíveis

### ✅ Endpoints Essenciais (Obrigatórios)

Estes são os **2 endpoints principais** que você precisa para integrar a IA:

#### 1. Descobrir Tabelas (Automático)

```http
POST /connections/{connection_id}/discover?space_id={space_id}
```

**Quando usar:** Após criar uma conexão BigQuery no seu backend.

**Resposta:**
```json
{
  "success": true,
  "connection_id": "xxx",
  "space_id": "xxx",
  "metadata_rows_inserted": 100,
  "tables_discovered": 6
}
```

**Parâmetros opcionais:**
- `run_in_background=true` - Executa em background (não bloqueia)

#### 2. Fazer Pergunta (Query)

```http
POST /connections/{connection_id}/query
Content-Type: application/json

{
  "question": "Qual é a performance de pageviews mensal?",
  "user_id": "user-123",
  "space_id": "00000000-0000-0000-0000-000000000001",
  "thread_id": "thread-456"  // opcional - para manter contexto de conversa
}
```

**Quando usar:** Quando o usuário fizer uma pergunta no seu frontend.

**Resposta:**
```json
{
  "answer": "A performance de pageviews mensal mostra...",
  "data_sample": [
    {"pageview_year": 2024, "pageview_month": 1, "total_pageviews": 890}
  ],
  "meta": {
    "detected_language": "pt",
    "chosen_table": "silver_pageviews_enriquecido",
    "sql": "SELECT pageview_year, pageview_month, COUNT(pageview_id)...",
    "num_rows": 24,
    "error": null
  }
}
```

### 📋 Endpoints Auxiliares (Opcionais)

Estes endpoints podem ser úteis mas **não são obrigatórios** para integração básica:

- `GET /health` - Verificar se a API está online
- `GET /connections` - Listar conexões (se você não gerencia isso no seu backend)
- `GET /connections/{id}` - Obter detalhes de uma conexão

> **Nota:** Se você já gerencia conexões no seu próprio backend, não precisa usar esses endpoints auxiliares.

## 📝 Exemplo Completo de Integração

```python
# seu_backend/services/ia_service.py
import httpx
from typing import Optional

class IAService:
    def __init__(self, ia_api_url: str):
        self.ia_api_url = ia_api_url
        self.client = httpx.AsyncClient(timeout=60.0)
    
    async def create_connection_with_auto_discover(
        self,
        connection_data: dict,
        auto_discover: bool = True
    ) -> dict:
        """
        Cria uma conexão e descobre tabelas automaticamente.
        """
        # 1. Criar conexão (seu código)
        connection = await self.create_connection(connection_data)
        
        # 2. Descobrir tabelas automaticamente
        if auto_discover:
            try:
                result = await self.discover_tables(
                    connection_id=connection["id"],
                    space_id=connection["space_id"]
                )
                connection["discovery"] = result
            except Exception as e:
                # Log erro mas não falha a criação da conexão
                print(f"⚠️ Erro na descoberta automática: {e}")
        
        return connection
    
    async def discover_tables(
        self,
        connection_id: str,
        space_id: str,
        background: bool = False
    ) -> dict:
        """Descobre tabelas de uma conexão"""
        response = await self.client.post(
            f"{self.ia_api_url}/connections/{connection_id}/discover",
            params={
                "space_id": space_id,
                "run_in_background": str(background).lower()
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def ask_question(
        self,
        connection_id: str,
        question: str,
        user_id: str,
        space_id: str,
        thread_id: Optional[str] = None
    ) -> dict:
        """Faz uma pergunta usando a IA"""
        response = await self.client.post(
            f"{self.ia_api_url}/connections/{connection_id}/query",
            json={
                "question": question,
                "user_id": user_id,
                "space_id": space_id,
                "thread_id": thread_id
            }
        )
        response.raise_for_status()
        return response.json()
```

## 🎯 Fluxo Recomendado (Mínimo Necessário)

Para integração básica, você precisa apenas de **2 passos**:

1. **Após criar conexão BigQuery** → Chame descoberta automática:
   ```python
   POST /connections/{connection_id}/discover?space_id={space_id}
   ```

2. **Quando usuário fizer pergunta** → Chame query:
   ```python
   POST /connections/{connection_id}/query
   ```

**Isso é tudo!** Com esses 2 endpoints você tem integração completa.

### Fluxo Completo Detalhado

1. **Usuário cria conexão BigQuery** no seu produto
2. **Seu backend chama descoberta automática** (endpoint 1)
3. **Sistema descobre todas as tabelas** automaticamente
4. **Usuário faz perguntas** via seu frontend
5. **Seu frontend chama query** (endpoint 2)
6. **IA responde** com SQL e dados formatados

## ⚙️ Configuração

### Variáveis de Ambiente

```bash
# URL da API da IA (se estiver em serviço separado)
IA_API_URL=http://localhost:8000

# Ou se estiver no mesmo serviço, use caminho relativo
IA_API_URL=http://localhost:8000
```

### Timeout

A descoberta de tabelas pode demorar alguns segundos (especialmente com muitos datasets). Configure timeout adequado:

```python
httpx.post(..., timeout=60.0)  # 60 segundos
```

## 🔒 Segurança

- Valide `space_id` no seu backend antes de chamar a IA
- Use autenticação/autorização adequada
- Considere rate limiting para queries

## 📊 Monitoramento

Os eventos são logados automaticamente:
- `discover_tables_start`
- `discover_tables_done`
- `api_query_connection`

Monitore esses eventos para debugging e analytics.

## 🐛 Troubleshooting

### Erro: "Nenhum metadata encontrado"
- Execute a descoberta primeiro: `POST /connections/{id}/discover`

### Erro: "Conexão não encontrada"
- Verifique se o `connection_id` está correto
- Verifique se a conexão existe no banco

### Timeout na descoberta
- Use `run_in_background=true` para não bloquear
- Ou aumente o timeout do cliente HTTP
