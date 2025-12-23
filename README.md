<<<<<<< HEAD
# IA POC - Intelligent Data Assistant

Sistema de assistente de dados inteligente com suporte a múltiplas fontes de dados, RAG e geração de SQL.

## Arquitetura

O projeto segue uma arquitetura modular com separação clara de responsabilidades:

- **api/**: FastAPI application com rotas e dependências
- **core/**: Lógica de negócio (auth, domain, data sources, RAG, SQL, agents, LLM)
- **db/**: Modelos SQLAlchemy e configuração de banco
- **config/**: Configurações e settings
- **agent_registry/**: Definições de agentes em YAML/JSON
- **worker/**: Celery workers para tarefas assíncronas
- **scripts/**: Scripts utilitários

## Instalação

1. Clone o repositório
2. Crie um ambiente virtual:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

3. Instale as dependências:
```bash
pip install -r requirements.txt
```

4. Configure o arquivo `.env` baseado em `.env.example`

5. Execute as migrações:
```bash
alembic upgrade head
```

## Execução

### API
```bash
python run_api.py
```

### Worker (Celery)
```bash
python run_worker.py
```

## Estrutura de Dados

- **Spaces**: Espaços de trabalho isolados
- **Crews**: Grupos de usuários dentro de um Space
- **Planets**: Conjuntos de tabelas/fontes de dados
- **Agents**: Agentes configuráveis para consultas
- **Connections**: Conexões com fontes de dados (BigQuery, Postgres, etc.)

## Desenvolvimento

Para adicionar novas fontes de dados, implemente a interface `BaseDataSource` em `core/data_sources/`.

Para criar novos agentes, adicione definições YAML em `agent_registry/examples/`.

=======
# sky-poc-ai
>>>>>>> origin/staging
