# POC Deploy - AI SaaS

Repositório de infraestrutura e deploy para a aplicação AI SaaS.

## Status do Deploy

![Deploy Status](https://github.com/sky-first/sky-poc-infra/workflows/Deploy%20Infrastructure/badge.svg)

**Últimos Deploys:**
- [Ver histórico completo](https://github.com/sky-first/sky-poc-infra/actions/workflows/deploy.yml)

**Ambientes:**
- **POC-SKY** - [Status](https://github.com/sky-first/sky-poc-infra/actions?query=workflow%3A%22Deploy+Infrastructure%22+environment%3Apoc-sky)
- **Staging** - [Status](https://github.com/sky-first/sky-poc-infra/actions?query=workflow%3A%22Deploy+Infrastructure%22+environment%3Astaging)
- **Production** - [Status](https://github.com/sky-first/sky-poc-infra/actions?query=workflow%3A%22Deploy+Infrastructure%22+environment%3Aprod)

## Estrutura

```
poc-deploy/
├── docker-compose.yml                    # Orquestração completa (backend + frontend + infra)
├── docker-compose.infrastructure.yml     # Apenas PostgreSQL + Redis
├── docker-compose.postgres-only.yml      # Apenas PostgreSQL
├── env.example                           # Template de variáveis de ambiente
├── access_server_azure.sh                # Script para acessar a VM do Azure
├── setup_server.sh                       # Script de configuração do servidor
├── scripts/
│   └── postgres/                        # Scripts de configuração/manutenção do PostgreSQL
│       ├── install_pgvector_ai_saas_db.sh
│       ├── configure_postgres_external.sh
│       ├── configure_postgres_safe.sh
│       ├── check_pgvector.sh
│       ├── check_postgres_connections.sh
│       ├── diagnose_postgres_connection.sh
│       └── setup_pgvector.sql
├── docker/
│   └── postgres/
│       ├── Dockerfile
│       └── init-pgvector.sh
└── infra/
    └── azure/                           # Infraestrutura Azure
        ├── main.tf
        ├── variables.tf
        ├── terraform.tfvars.example
        └── README.md
```

## Uso Rápido

### Deploy apenas PostgreSQL

```bash
docker compose -f docker-compose.postgres-only.yml up -d
```

### Deploy completo

```bash
docker compose up -d --build
```

> Observação: as migrações Alembic agora rodam em um serviço dedicado `migrate` antes de subir backend/worker/beat. Esses serviços só iniciam após o `migrate` concluir com sucesso.

## Pré-requisitos

- Docker e Docker Compose instalados
- Arquivo `.env` configurado (copie de `env.example`)
- Repositórios `backend`, `frontend` e `ia` clonados lado a lado

## Configuração do Arquivo .env

Copie o arquivo de exemplo e configure as variáveis:

```bash
cp env.example .env
```

**Gerar valores seguros:**

```bash
# Gerar senha PostgreSQL
openssl rand -base64 32

# Gerar senha Redis
openssl rand -base64 32

# Gerar JWT Secret Key
openssl rand -hex 32

# Gerar Encryption Key
openssl rand -hex 32
```

Substitua os valores padrão no arquivo `.env` pelos valores gerados acima.

## Infraestrutura Azure

Este projeto usa **Azure** para hospedar a infraestrutura:

### Azure (Virtual Machines)
- Infraestrutura: `infra/azure/`
- Acesso: `./access_server_azure.sh` (usa SSH)
- Documentação completa: [`infra/azure/README.md`](infra/azure/README.md)
- Estado remoto Terraform: configure Azure Storage + container e informe os secrets no GitHub (`TF_BACKEND_RESOURCE_GROUP`, `TF_BACKEND_STORAGE_ACCOUNT`, `TF_BACKEND_CONTAINER`, `TF_BACKEND_KEY_PREFIX`). O workflow cria `backend.hcl` e usa lock no storage.

#### Dry-run local (antes de rodar o workflow)

Para pegar erros de `terraform init/validate/plan` antes do GitHub Actions, rode:

```powershell
# 1) Garanta que você está autenticado no Azure
az login

# 2) (Opcional, para testar igual ao CI com estado remoto) defina as variáveis do backend
$env:TF_BACKEND_RESOURCE_GROUP  = "<rg-do-backend>"
$env:TF_BACKEND_STORAGE_ACCOUNT = "<storage-account-do-backend>"
$env:TF_BACKEND_CONTAINER       = "<container-do-backend>"   # ex: tfstate
$env:TF_BACKEND_KEY_PREFIX      = "poc-deploy"               # opcional

# 3) Rodar o dry-run (usa Terraform via Docker)
.\scripts\run-terraform-ci-dryrun.ps1 -Environment staging -TerraformVersion 1.9.0
```

**Para começar:**

**1. Instalar Azure CLI:**

**Windows (PowerShell):**
```powershell
# Opção 1: Usando script automatizado (recomendado)
.\install_azure_cli.ps1

# Opção 2: Usando winget (não requer admin)
winget install -e --id Microsoft.AzureCLI

# Opção 3: Baixar instalador manualmente
# https://aka.ms/installazurecliwindows
```

**macOS/Linux:**
```bash
brew install azure-cli
```

**2. Fazer login:**
```bash
az login
```

**3. Configurar Terraform:**
```bash
cd infra/azure
cp terraform.tfvars.example terraform.tfvars
# Edite terraform.tfvars com suas configurações
```

**4. Criar infraestrutura:**
```bash
terraform init
terraform plan
terraform apply



**Pré-requisitos:**
- Azure CLI instalado e configurado
- Chave SSH configurada

Para mais detalhes, consulte: [`infra/azure/README.md`](infra/azure/README.md)

**Segredos via Key Vault (deploy automatizado):**
- Crie/defina o Key Vault e os segredos: `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, `SENTRY_DSN` (nomes podem ser customizados).
- Adicione secrets no GitHub: `KEYVAULT_NAME`, `KV_POSTGRES_PASSWORD_SECRET`, `KV_REDIS_PASSWORD_SECRET`, `KV_JWT_SECRET_SECRET`, `KV_ENCRYPTION_KEY_SECRET`, `KV_SENTRY_DSN_SECRET`.
- O job `update-vm-code` busca esses segredos e gera `~/projeto/poc-deploy/.env` antes de restartar os containers.

## Estrutura Esperada no Servidor

```
~/projeto/
├── poc-deploy/
├── backend/
├── frontend/
└── ia/
```

## Configuração de Acesso ao PostgreSQL

### IMPORTANTE: Configurar Network Security Group

Se você não consegue conectar ao PostgreSQL, verifique se a porta 5433 está aberta no Network Security Group do Azure. Para corrigir:

```bash
# 1. Aplicar mudanças no Terraform
cd infra/azure
terraform plan   # Ver o que será alterado
terraform apply  # Aplicar as mudanças

# Isso vai adicionar a regra de entrada para a porta 5433 no NSG
```

### Como Conectar ao PostgreSQL

Após aplicar as mudanças do Terraform, você pode conectar usando:

**String de conexão:**
```
Host: <IP_PUBLICO_DA_VM_AZURE>
Port: 5433
Database: ai_saas_db
User: postgres
Password: <POSTGRES_PASSWORD do arquivo .env>
```

**Exemplos de conexão:**

**Via psql (linha de comando):**
```bash
psql -h <IP_DA_INSTANCIA> -p 5433 -U postgres -d ai_saas_db
```

**Via DBeaver / pgAdmin:**
- Host: `<IP_DA_INSTANCIA>` (ou `localhost` se conectando localmente)
- Port: `5433`
- Database: `ai_saas_db`
- Username: `postgres`
- Password: `<valor de POSTGRES_PASSWORD do .env>`

**Nota:** Se você está conectando do próprio servidor Azure, use `localhost`. Se está conectando de outro computador, use o IP público da VM Azure.

**Via Python (psycopg2):**
```python
import psycopg2

conn = psycopg2.connect(
    host="<IP_DA_INSTANCIA>",
    port=5433,
    database="ai_saas_db",
    user="postgres",
    password="<POSTGRES_PASSWORD>"
)
```

**Via SQLAlchemy:**
```python
from sqlalchemy import create_engine

engine = create_engine(
    f"postgresql://postgres:<POSTGRES_PASSWORD>@<IP_DA_INSTANCIA>:5433/ai_saas_db"
)
```

### Verificar se o PostgreSQL está rodando

```bash
# No servidor Azure
docker ps | grep postgres
docker logs ai_saas_postgres_prod

# Testar conexão localmente (do seu computador)
telnet <IP_DA_VM> 5433
# ou
nc -zv <IP_DA_VM> 5433
```

## Configurar Número Máximo de Conexões do PostgreSQL

Para aumentar o número máximo de conexões simultâneas permitidas pelo PostgreSQL:

### PostgreSQL em Docker



Este script:
-  Verifica memória disponível antes de configurar
-  Modifica `max_connections` no arquivo `postgresql.conf` (padrão: 300 conexões)
-  Configura `work_mem` para evitar uso excessivo de memória (padrão: 2MB)
-  Aplica outras otimizações (shared_buffers, effective_cache_size)
-  Reinicia o container PostgreSQL para aplicar as mudanças
-  Verifica se a configuração foi aplicada corretamente

**Verificar configuração atual:**
```bash
# No servidor Azure
docker exec ai_saas_postgres_prod psql -U postgres -c "SHOW max_connections;"
docker exec ai_saas_postgres_prod psql -U postgres -c "SHOW work_mem;"
```

**Nota:** O valor padrão do PostgreSQL é 100 conexões. O script configura **300 conexões** como padrão. Se precisar de valores diferentes, você pode especificar: `./scripts/postgres/configure_postgres_safe.sh [max_connections] [work_mem_mb]`

## Liberar Acesso Externo ao PostgreSQL

Se você está recebendo "conexão recusada" ao tentar conectar de outro computador:

**1. Network Security Group do Azure (já aplicado):**
```bash
# O Terraform já foi aplicado e a porta 5433 está liberada no NSG
cd infra/azure
terraform apply  # Se necessário
```



Este script vai:
- Configurar `pg_hba.conf` para aceitar conexões externas
- Configurar `postgresql.conf` para escutar em todas as interfaces
- Liberar a porta 5433 no firewall local (UFW)
- Reiniciar o container PostgreSQL

**3. Informações de conexão:**
- **Host:** `<IP_PUBLICO_DA_VM_AZURE>` (obtenha com `terraform output -json` em `infra/azure/`)
- **Port:** `5433`
- **Database:** `ai_saas_db`
- **Username:** `postgres`
- **Password:** Valor de `POSTGRES_PASSWORD` no arquivo `.env`

## Troubleshooting - Problemas de Conexão

### Script de Diagnóstico Automático

**Execute primeiro o script de diagnóstico para identificar o problema:**


Este script verifica automaticamente:
-  Se o container está rodando
-  Se a porta 5433 está escutando
-  Configuração do PostgreSQL (listen_addresses e pg_hba.conf)
-  Firewall local (UFW)
-  Logs do PostgreSQL
-  Conexão local
-  Network Security Group do Azure

### Problema: Não consigo conectar ao PostgreSQL de outro computador

**1. Execute o diagnóstico primeiro:**
```bash
cd ~/poc-deploy
./scripts/postgres/diagnose_postgres_connection.sh
```

**2. Verifique se o container está rodando:**
```bash
# No servidor Azure
docker ps | grep postgres
# Se não estiver rodando:
docker compose -f docker-compose.postgres-only.yml up -d
```

**2. Verifique o firewall local (UFW):**
```bash
# No servidor Azure
sudo ufw status
# Se estiver ativo e bloqueando:
sudo ufw allow 5433/tcp
sudo ufw reload
```

**3. Verifique se a porta está escutando:**
```bash
# No servidor Azure
sudo netstat -tlnp | grep 5433
# ou
sudo ss -tlnp | grep 5433
```

**4. Verifique os logs do PostgreSQL:**
```bash
# No servidor Azure
docker logs -f ai_saas_postgres_prod
```

**5. Teste a conexão do próprio servidor:**
```bash
# No servidor Azure
docker exec -it ai_saas_postgres_prod psql -U postgres -d ai_saas_db
# Se funcionar, o problema é de rede/firewall
```

**6. Verifique se o Network Security Group do Azure está correto:**
```bash
# No seu computador local
cd infra/azure
terraform output vm_public_ip  # Anote o IP
# Verifique no portal do Azure se a regra da porta 5433 existe no NSG
```

**7. Teste a conectividade TCP:**
```bash
# Do seu computador local
telnet <IP_DA_INSTANCIA> 5433
# Se não conectar, o problema é firewall/rede
```

### Problemas Comuns:

- **"Connection refused"**: 
  - Container não está rodando → `docker compose -f docker-compose.postgres-only.yml up -d`
  - Porta não está mapeada → Verifique `docker-compose.postgres-only.yml`
  - PostgreSQL não está escutando em todas as interfaces → Execute `./scripts/postgres/configure_postgres_external.sh`
  
- **"Connection timeout"**: 
  - Network Security Group do Azure bloqueando → Execute `cd infra/azure && terraform apply`
  - Firewall local (UFW) bloqueando → Execute `sudo ufw allow 5433/tcp`
  - Verifique com: `./scripts/postgres/diagnose_postgres_connection.sh`
  
- **"Authentication failed"**: 
  - Senha incorreta no arquivo `.env`
  - Verifique se `POSTGRES_PASSWORD` está correto
  
- **"Database does not exist"**: 
  - Verifique se `POSTGRES_DB` está correto no `.env`
  - O valor padrão é `ai_saas_db`

### Checklist de Resolução de Problemas

Execute na ordem:

1.  **Execute o diagnóstico**: `./scripts/postgres/diagnose_postgres_connection.sh`
2.  **Verifique o container**: `docker ps | grep postgres`
3.  **Configure PostgreSQL**: `./scripts/postgres/configure_postgres_external.sh`
4.  **Verifique Network Security Group**: `cd infra/azure && terraform apply`
5.  **Teste conectividade TCP**: `telnet <IP_DA_VM> 5433`

## Backup do PostgreSQL para Azure Blob

Para ter RPO/RTO melhores, faça dump periódico do Postgres para o Blob Storage:

1. Pré-requisitos:
   - `az` CLI autenticado (`az login`)
   - Variáveis exportadas: `STORAGE_ACCOUNT`, `STORAGE_CONTAINER`, `STORAGE_SAS_TOKEN` (ou `AZURE_STORAGE_KEY`)
   - Postgres rodando (container `ai_saas_postgres_prod` ou ajuste `POSTGRES_CONTAINER`)

2. Rodar o backup:
   ```bash
   cd ~/projeto/poc-deploy
   export STORAGE_ACCOUNT=...
   export STORAGE_CONTAINER=...
   export STORAGE_SAS_TOKEN='?sv=...'
   ./scripts/postgres/backup_to_azure.sh
   ```

3. O arquivo é enviado para o container Blob em `backups/pgdump-<db>-<timestamp>.sql.gz`.

4. Agendamento (exemplo cron na VM):
   ```cron
   0 3 * * * cd ~/projeto/poc-deploy && /usr/bin/env \
     STORAGE_ACCOUNT=... \
     STORAGE_CONTAINER=... \
     STORAGE_SAS_TOKEN='?sv=...' \
     ./scripts/postgres/backup_to_azure.sh >> /var/log/pg-backup.log 2>&1
   ```

5. Restore (manual):
   - Baixe o `.sql.gz` e rode `gunzip -c dump.sql.gz | psql -h <host> -U <user> -d <db>`

## Instalação e Configuração do pgvector

O pgvector é uma extensão do PostgreSQL para armazenar e buscar embeddings vetoriais (usado para RAG - Retrieval Augmented Generation).

### IMPORTANTE

O pgvector **não pode ser instalado apenas pelo DBeaver**. É uma extensão de sistema que precisa estar instalada no host do PostgreSQL. O DBeaver apenas executa SQL; o pacote precisa estar instalado no servidor.


Este script:
-  Detecta automaticamente se está rodando em Docker ou PostgreSQL nativo
-  Verifica se o pgvector já está disponível
-  Instala o pacote se necessário (Debian/Ubuntu/RHEL/CentOS)
-  Cria a extensão `vector` no banco `ai_saas_db`
-  Cria a tabela `embeddings` pronta para uso

### Instalação Manual via DBeaver

Se preferir fazer manualmente pelo DBeaver:

**1. Verificar se o pacote está disponível:**

```sql
SELECT * FROM pg_available_extensions WHERE name = 'vector';
```

Se não aparecer nenhum resultado, o pacote não está instalado no servidor. Você precisa instalar no host do PostgreSQL.

**2. Descobrir versão do PostgreSQL:**

```sql
SELECT version();
```

Anote a versão major (ex.: 15, 14, 13).

**3. Instalar no servidor (via SSH/terminal):**

**Debian/Ubuntu:**
```bash
sudo apt-get update
sudo apt-get install postgresql-15-pgvector  # Ajuste a versão conforme necessário
```

**RHEL/CentOS/Amazon Linux:**
```bash
sudo yum install postgresql15-pgvector  # Ajuste a versão conforme necessário
```

**Docker (se necessário instalar manualmente):**
```bash
docker exec ai_saas_postgres_prod apt-get update
docker exec ai_saas_postgres_prod apt-get install -y postgresql-14-pgvector
docker restart ai_saas_postgres_prod
```

**4. Criar extensão no banco (no DBeaver):**

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

**5. Criar tabela embeddings (no DBeaver):**

Execute o arquivo `scripts/postgres/setup_pgvector.sql` ou execute manualmente:

```sql
CREATE TABLE IF NOT EXISTS embeddings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL,
  crew_id uuid NULL,
  user_id uuid NULL,
  table_metadata_id uuid NULL,
  document_id text NULL,
  embedding vector(3072) NOT NULL,
  text text NOT NULL,
  metadata jsonb NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_space ON embeddings(space_id);
```

### Arquivos Disponíveis

- **`scripts/postgres/install_pgvector_ai_saas_db.sh`**: Script automatizado para instalação completa (instala pgvector e cria extensão no banco ai_saas_db)
- **`scripts/postgres/setup_pgvector.sql`**: Script SQL completo para execução manual no DBeaver (cria extensão e tabela embeddings)
- **`scripts/postgres/check_pgvector.sh`**: Script de diagnóstico para verificar status do pgvector
- **`docker/postgres/init-pgvector.sh`**: Script de inicialização do Docker (cria extensão e tabela automaticamente)

### Verificação

Após a instalação, verifique se tudo está funcionando:

```sql
-- Verificar extensão
SELECT * FROM pg_extension WHERE extname = 'vector';

-- Verificar tabela
SELECT * FROM information_schema.tables WHERE table_name = 'embeddings';

-- Ver estrutura da tabela
\d embeddings
```

### Nota sobre Docker

A imagem Docker usada (`pgvector/pgvector:pg14`) já vem com o pgvector pré-instalado. O script `init-pgvector.sh` cria automaticamente a extensão e a tabela quando o banco é inicializado pela primeira vez.

Se você está usando Docker e a extensão não está disponível, pode ser necessário:
1. Reconstruir a imagem: `docker compose build postgres`
2. Recriar o container: `docker compose down -v && docker compose up -d`

