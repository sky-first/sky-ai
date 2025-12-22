# sky-poc-ai

Pipeline e mocks para LangGraph + OpenAI.

## LLM
- `get_llm()` em `src/llm/provider.py` devolve `MockLLM` quando `ENV=ci`, garantindo zero chamadas externas no CI.
- Produção usa `OpenAI` com timeout conservador; defina `OPENAI_API_KEY`, `OPENAI_MODEL` e `TEMPERATURE` no runtime.
- Nunca logue prompts, respostas ou API keys; sanitize entradas antes de enviar ao modelo; aplique rate limiting no runtime.

## CI
- Workflow `/.github/workflows/ci.yml` roda em PRs e pushes para `main`/`develop` (mock LLM, zero chamadas externas).
- Passos: upgrade de `pip`, instalar deps, `flake8 src tests`, `pytest tests`.

## CD / Staging
- Workflow `/.github/workflows/deploy-staging.yml` roda em push para `develop`/`staging` ou manual (`workflow_dispatch`): lint, testes (mock), build da imagem Docker (sem push).
- Branch flow sugerido: feature → PR para `develop`/`staging` → merge dispara build de staging → depois PR/tag para `main` para produção.
- Proteções recomendadas: proibir push direto em `develop`/`main`, exigir checks do CI e 1+ review.

## Docker
- `Dockerfile` define `ENV=prod` e `OPENAI_API_KEY` vazio por padrão; deploy real injeta `OPENAI_API_KEY`, `OPENAI_MODEL`, `TEMPERATURE`.
- `CMD` é placeholder; ajuste para o entrypoint da aplicação quando disponível.

## Testes locais
```
pip install -r requirements.txt -r requirements-dev.txt
pytest
flake8 src tests
```