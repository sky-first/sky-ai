# Requisitos de Integração: Frontend <-> AI

Este documento detalha as mudanças realizadas no Backend e o que precisa ser ajustado no Frontend para consumir as novas funcionalidades de IA.

## 1. Geração Dinâmica de Títulos (Disponível)

### Backend
- **Rota**: `POST /connections/{id}/query` (e streaming)
- **Novo Campo**: `response.meta.title`
- **Comportamento**: Retorna um título descritivo gerado no momento da execução (ex: "Monthly Sales 2024") baseado nos dados reais.

### Frontend (A Fazer)
- **Widget**: Ao exibir resposta de query, usar `response.meta.title` como título visível do gráfico/tabela.
- **Persistência**: Ao salvar o widget, usar esse título como default.

---

## 2. Explicação de Edição SQL (Novo!) 🚀

Nova funcionalidade que permite à IA explicar os resultados de um SQL editado manualmente pelo usuário.

### Endpoint
- **Rota**: `POST /connections/{id}/validate-sql`

### Request (Frontend -> Backend)
O Frontend deve enviar dois novos campos opcionais quando o usuário clicar em "Run" (Validar/Executar) no editor de SQL:

1.  `include_explanation`: `true` (boolean)
    - Envie `true` se quiser que a IA gere o texto explicativo sobre os novos dados.
    - *Recomendação*: Enviar `true` sempre que o usuário executar uma query manual, para manter a experiência de "AI Assistant" ativa.
2.  `question`: `string` (opcional)
    - A pergunta original do usuário (ex: "Show me sales").
    - Isso ajuda a IA a contextualizar a explicação ("Based on your question about sales..."). Se não tiver, envie `null` ou string vazia.

**Exemplo de Payload Completo**:
```json
{
  "sql": "SELECT * FROM sales WHERE amount > 1000 LIMIT 10",
  "user_id": "user-123",
  "space_id": "space-456",
  "include_explanation": true,
  "question": "How are my sales?"
}
```

### Response (Backend -> Frontend)
O backend retornará um novo campo `explanation` dentro do objeto de resposta.

- **Campo**: `explanation` (string | null)
- **Comportamento**: Contém um parágrafo curto (em Inglês, máx 3 frases) resumindo os insights dos dados retornados.
- **Exemplo**:
  ```json
  {
    "is_valid": true,
    "preview_data": [{"col": "val"}],
    "explanation": "The data shows high average sales ($5,200) across the filtered region, indicating strong performance.",
    "execution_time_ms": 120
  }
  ```

### Ação na UI
1.  **Grid de Resultados**: Ao lado ou acima da tabela de preview, exibir um bloco de texto (ex: com ícone de ✨).
2.  **Conteúdo**: Inserir o texto recebido em `explanation`.
3.  **Loading**: Enquanto o `validate-sql` roda, mostrar estado de loading também na explicação (já que a IA adiciona leve latência).
