# Guia de Teste Local - Fase 1

## Script de Validação Local

O script `test-local-deploy.sh` valida todos os itens do checklist antes de fazer deploy na VM.

## Como Usar

### 1. Executar Validação Básica

```bash
cd sky-poc-infra
./scripts/test-local-deploy.sh
```

### 2. Com Token GitHub (Recomendado)

Para validar acesso aos repositórios privados:

```bash
export GH_PAT=seu_personal_access_token
./scripts/test-local-deploy.sh
```

**Como criar GH_PAT:**
1. Acesse: https://github.com/settings/tokens
2. Clique em "Generate new token (classic)"
3. Dê um nome (ex: "Deploy Local")
4. Selecione escopo: `repo` (acesso completo a repositórios)
5. Gere o token e copie
6. Configure: `export GH_PAT=ghp_seu_token_aqui`

### 3. Preparar Ambiente Local

Antes de executar o teste, prepare o ambiente:

```bash
# Do diretório raiz (poc:deploy:sky)
./setup-local.sh
```

Isso vai:
- Criar arquivos `.env` com senhas geradas
- Configurar ambientes Python
- Instalar dependências

## O que o Script Valida

### ✅ Item 1: Acesso aos Repositórios
- Verifica acesso aos 4 repositórios via GitHub API
- Valida se GH_PAT ou GITHUB_TOKEN está configurado
- Testa se repositórios são públicos ou privados

### ✅ Item 2: Secrets / .env
- Verifica se `.env` existe
- Valida variáveis obrigatórias:
  - `POSTGRES_PASSWORD`
  - `REDIS_PASSWORD`
  - `JWT_SECRET_KEY`
  - `ENCRYPTION_KEY`
  - `CORS_ORIGINS`
  - `NEXT_PUBLIC_API_URL`
- Verifica permissões do arquivo (deve ser 600)

### ✅ Item 3: Estrutura de Diretórios
- Valida que os 4 repositórios estão clonados:
  - `../sky-poc-backend`
  - `../sky-poc-frontend`
  - `../sky-poc-ai`
  - `sky-poc-infra` (atual)
- Verifica contexts no `docker-compose.yml`

### ✅ Item 4: Pré-requisitos
- Docker instalado e rodando
- Docker Compose instalado
- Git instalado e configurado

### ✅ Item 5: Scripts Compatíveis
- Verifica se scripts usam `set -eu` (compatível com RunShellScript)
- Verifica se não usam `pipefail` (não suportado)
- Valida que scripts falham corretamente com `exit 1`

### ✅ Item 6: Terraform
- Verifica se arquivos `terraform.tfvars.*` existem
- Valida se Terraform está instalado (opcional)

### ✅ Item 7: Docker Compose
- Valida sintaxe do `docker-compose.yml`
- Verifica se contexts existem

### ✅ Item 8: Health Checks
- Verifica se health checks estão configurados no docker-compose.yml

## Interpretando os Resultados

### ✅ Tudo OK
```
✅✅✅ VALIDAÇÃO COMPLETA: TUDO OK!
Pronto para Fase 2: Deploy Local na VM
```

**Próximo passo:** Execute `./scripts/deploy-local-to-vm.sh`

### ⚠️ Avisos (Warnings)
```
⚠️  VALIDAÇÃO OK com X aviso(s)
Recomendado revisar avisos antes de continuar
```

**Ação:** Revise os avisos, mas pode continuar se não forem críticos.

### ❌ Erros
```
❌ VALIDAÇÃO FALHOU com X erro(s)
Corrija os erros antes de continuar
```

**Ação:** Corrija todos os erros antes de prosseguir.

## Problemas Comuns

### Docker não está rodando
**Solução:**
- macOS: Abra o Docker Desktop
- Linux: `sudo systemctl start docker`

### .env não encontrado
**Solução:**
```bash
cd sky-poc-infra
cp env.example .env
# Edite .env com valores reais
```

### Repositórios não acessíveis
**Solução:**
```bash
export GH_PAT=seu_token
./scripts/test-local-deploy.sh
```

### Permissões do .env incorretas
**Solução:**
```bash
chmod 600 sky-poc-infra/.env
```

## Próximos Passos

Após passar na validação:

1. **Fase 2:** Deploy local na VM
   ```bash
   export VM_IP=172.191.77.30
   export GH_PAT=seu_token
   ./scripts/deploy-local-to-vm.sh
   ```

2. **Fase 3:** Configurar GitHub Actions para deploy automático


