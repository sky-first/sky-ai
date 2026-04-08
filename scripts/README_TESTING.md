# Script de Testes Automatizados

## 📋 Visão Geral

O script `test_suite.py` executa uma suíte completa de testes automatizados do pipeline de IA, validando:
- Geração de SQL
- Escolha de tabelas pelo orchestrator
- Execução de queries no BigQuery
- Geração de respostas em linguagem natural
- Validação de palavras-chave esperadas

## 🚀 Uso Básico

```bash
# Executar todos os testes padrão
python3 scripts/test_suite.py

# Com variáveis de ambiente customizadas
TEST_SPACE_ID="..." TEST_CONNECTION_ID="..." python3 scripts/test_suite.py
```

## 📝 Opções de Linha de Comando

```bash
# Modo verbose (mostra detalhes de cada teste)
python3 scripts/test_suite.py --verbose

# Testar uma pergunta específica
python3 scripts/test_suite.py --question "Quantos clientes temos?"

# Salvar relatório em arquivo customizado
python3 scripts/test_suite.py --report my_test_report.json

# Combinar opções
python3 scripts/test_suite.py --verbose --report ci_report.json
```

## 🔧 Variáveis de Ambiente

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `TEST_SPACE_ID` | ID do Space de teste | `00000000-0000-0000-0000-000000000001` |
| `TEST_CONNECTION_ID` | ID da Connection de teste | `00000000-0000-0000-0000-000000000002` |
| `TEST_CREW_ID` | ID do Crew (opcional) | `None` |
| `TEST_QUESTION` | Pergunta única (sobrescreve suíte) | `None` |

## 📊 Saída

O script gera:

1. **Saída no console**: Resumo dos testes em tempo real
2. **Relatório JSON**: Arquivo `test_report.json` com detalhes completos

### Formato do Relatório JSON

```json
{
  "summary": {
    "total": 4,
    "passed": 3,
    "failed": 1,
    "success_rate": "75.0%",
    "total_time_seconds": 32.42
  },
  "timestamp": "2025-12-11T13:03:45.318694",
  "environment": {
    "TEST_SPACE_ID": "...",
    "TEST_CONNECTION_ID": "...",
    "TEST_CREW_ID": "None"
  },
  "results": [
    {
      "question": "...",
      "success": true,
      "sql_generated": "...",
      "answer": "...",
      "execution_time": 10.35,
      ...
    }
  ]
}
```

## ✅ Exit Codes

- `0`: Todos os testes passaram
- `1`: Um ou mais testes falharam
- `130`: Testes interrompidos (Ctrl+C)

## 🧪 Suíte de Testes Padrão

O script inclui 4 testes padrão:

1. **Listagem de países** - Testa SELECT DISTINCT
2. **Contagem de clientes** - Testa agregação COUNT
3. **Valor total de faturas** - Testa agregação SUM
4. **Últimos pagamentos** - Testa ORDER BY e LIMIT

## 🔄 Uso em CI/CD

```yaml
# Exemplo GitHub Actions
- name: Run Tests
  run: |
    python3 scripts/test_suite.py --report ci_report.json
  env:
    TEST_SPACE_ID: ${{ secrets.TEST_SPACE_ID }}
    TEST_CONNECTION_ID: ${{ secrets.TEST_CONNECTION_ID }}
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

## 📈 Interpretando Resultados

- **✅ PASSOU**: Teste executou com sucesso e gerou SQL + resposta
- **❌ FALHOU**: Erro na execução ou validação falhou
- **⚠️ Avisos**: Validações não críticas (ex: tabela diferente da esperada)

## 🛠️ Customização

Para adicionar novos testes, edite a lista `DEFAULT_TEST_QUESTIONS` no arquivo `test_suite.py`.




