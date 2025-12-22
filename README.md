# sky-poc-ai

Pipeline e mocks para LangGraph + OpenAI.

## LLM
- `get_llm()` em `src/llm/provider.py` devolve `MockLLM` quando `ENV=ci`, garantindo zero chamadas externas no CI.
- Produção usa `OpenAI` com timeout conservador; defina `OPENAI_API_KEY`, `OPENAI_MODEL` e `TEMPERATURE` no runtime.
- Nunca logue prompts, respostas ou API keys; sanitize entradas antes de enviar ao modelo; aplique rate limiting no runtime.

## CI
- Workflow `/.github/workflows/ci.yml` roda em PRs para `main` e `develop` com `ENV=ci` e `OPENAI_API_KEY=dummy-key`.
- Passos: instalar deps, `flake8 src tests`, `pytest tests` (LLM mockado).

## Docker/CD
- Imagens devem vir com `ENV=prod` e `OPENAI_API_KEY` vazio por padrão; deploy real injeta `OPENAI_API_KEY`, `OPENAI_MODEL` e `TEMPERATURE`.
- CD apenas builda, versiona e publica a imagem; não chama OpenAI.

## Testes locais
```
pip install -r requirements.txt -r requirements-dev.txt
pytest
flake8 src tests
```