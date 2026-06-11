# Fase 1 — Suporte Bilíngue EN/PT

## Objetivo

Tornar o suporte a inglês e português robusto, determinístico e extensível — sem depender de detecção estatística frágil como única fonte de verdade.

## Arquitetura de idioma (após Fase 1)

```
locale (se plataforma enviar)
   ↓ senão
idioma travado da thread (chat_history)
   ↓ senão
langdetect(pergunta atual)
   ↓ senão
"en" (fallback seguro)
```

Essa cadeia é implementada em `core/i18n/i18n.py` e consumida por todos os pontos de decisão de idioma.

## Arquivos modificados

| Arquivo | O que mudou |
|---------|-------------|
| `core/i18n/i18n.py` | Adicionadas: `resolve_language()`, `language_decision()`, `unsupported_language_message()`, `thread_language_from_history()`, `_normalize_lang_code()` |
| `core/llm/orchestrator.py` | Gatekeeper e idioma da resposta usam a cadeia de prioridade; lista de afirmações substituída por `_detect_confirmation()` |
| `core/auth/models.py` | `UserContext.locale` agora `Optional[str] = None` (era `"en"` fixo) |
| `core/agents/generic_sql_agent.py` | Propaga `locale=None` em vez de `"en"` |
| `core/llm/context/builder.py` | Bundle de contexto à prova de `locale=None` |
| `api/schemas.py` | Campo `locale: Optional[str]` adicionado ao `QueryRequest` |
| `api/routes/connection_query.py` | Import atualizado; gatekeepers não-streaming e streaming usam `language_decision()` + `unsupported_language_message()`; bug SSE `\\n\\n` corrigido |

## Casos validados (testes temporários — Tarefas 1–5)

### Tarefa 1 — Função central de resolução

| Caso | Input | Resultado esperado |
|------|-------|-------------------|
| Locale vence tudo | `locale="pt-BR"`, thread="en", pergunta EN | `"pt"` |
| Thread sticky vence detecção | `thread_language="pt"`, pergunta="sim" | `"pt"` |
| "sim" em thread PT não vira inglês | thread PT, `question="sim"` | `"pt"` |
| Detecção usada sem locale/thread | pergunta longa em PT | `"pt"` |
| Locale não suportado cai na detecção | `locale="fr"`, pergunta EN | `"en"` |
| Sem sinal nenhum | pergunta vazia | `"en"` |
| Sempre devolve EN ou PT | pergunta em espanhol | `"en"` ou `"pt"` |

### Tarefa 2 — Idioma sticky por thread

| Caso | Input | Resultado esperado |
|------|-------|-------------------|
| Histórico vazio | `chat_history=None` | `None` |
| Primeiro user message em PT | histórico com msg PT longa | `"pt"` |
| Ignora msgs de assistant e msgs curtas | histórico misto | idioma da primeira msg substancial do user |
| Follow-up curto herda thread PT | `"sim"` + thread PT | `"pt"` |

### Tarefa 3 — Campo locale conectado

| Caso | Input | Resultado esperado |
|------|-------|-------------------|
| `QueryRequest` sem locale | `question="oi"` | `locale=None` |
| `QueryRequest` com locale | `locale="pt-BR"` | `locale="pt-BR"` preservado |
| `UserContext` sem locale | construção padrão | `locale=None` |
| Locale explícito vence thread + detecção | `locale="pt-BR"`, thread EN, pergunta EN | `"pt"` |

### Tarefa 4 — Gatekeeper + mensagem bilíngue

| Caso | Input | Resultado esperado |
|------|-------|-------------------|
| Francês sem locale nem thread | pergunta longa em FR | `blocked=True` |
| Pergunta EN válida | pergunta longa em EN | `blocked=False`, `lang="en"` |
| Locale suportado evita bloqueio | `locale="pt-BR"`, pergunta em FR | `blocked=False`, `lang="pt"` |
| Thread EN/PT evita bloqueio | `thread_language="pt"`, pergunta em FR | `blocked=False`, `lang="pt"` |
| Mensagem de bloqueio bilíngue | `unsupported_language_message()` | contém EN e PT |

### Tarefa 5 — Confirmação via LLM

| Caso | Input | Resultado esperado |
|------|-------|-------------------|
| Fast-path "sim" | `"sim"` | `(True, 0)` sem chamar LLM |
| Fast-path "yes" | `"yes"` | `(True, 0)` sem chamar LLM |
| LLM decide ambíguo PT | `"manda o segundo"` | `(True, 1)` |
| LLM decide nova pergunta | `"quais foram as vendas da semana?"` | `(False, -1)` |
| LLM com erro/timeout | exceção | `(False, -1)` — trata como nova pergunta |
| LLM alucina índice fora do range | `chosen_index: 9` pra lista de 3 | `(False, -1)` |

## O que NÃO foi feito (Fase 2)

- **Negociação proativa de idioma:** a IA detectar mudança de idioma e perguntar "quer que eu continue em português?" — requer estado adicional entre turnos.
- **Seletor de idioma na plataforma:** o campo `locale` está pronto no backend; falta a UI expor a preferência do usuário e enviar no request.
