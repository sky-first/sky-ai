# 🚀 Guia de Deploy Local na VM - Fase 2

## Script de Deploy Local para VM

O script `deploy-local-to-vm.sh` simula o que o GitHub Actions faz, mas executado localmente na VM.

## Pré-requisitos

### 1. Fase 1 Completa ✅
```bash
cd sky-poc-infra
./scripts/test-local-deploy.sh
# Deve passar sem erros críticos
```

### 2. Configurações Necessárias

```bash
# OBRIGATÓRIO
export VM_IP=172.191.77.30  # IP da sua VM

# OPCIONAL (mas recomendado)
export BRANCH=staging  # Branch a usar (padrão: staging)
export GH_PAT=seu_token  # Se repositórios forem privados
export SSH_KEY=/caminho/para/chave  # Se chave não estiver em keys/azure/id_rsa
```

### 3. Arquivo .env Local
```bash
cd sky-poc-infra
# Se não tiver .env:
cp env.example .env
./scripts/fix-env-secrets.sh  # Gera senhas seguras
```

## Como Usar

### Passo 1: Configurar Variáveis

```bash
export VM_IP=172.191.77.30
export BRANCH=staging

# Se repositórios forem privados:
export GH_PAT=ghp_seu_token_aqui
```

### Passo 2: Executar Deploy

```bash
cd sky-poc-infra
./scripts/deploy-local-to-vm.sh
```

## O que o Script Faz

### ✅ Item 1: Acesso aos Repositórios
- Configura autenticação Git na VM (se GH_PAT fornecido)
- Clona/atualiza os 4 repositórios na branch especificada
- Valida que branches existem antes de clonar

### ✅ Item 2: Secrets / .env
- Envia arquivo `.env` local para a VM
- Valida variáveis obrigatórias:
  - `POSTGRES_PASSWORD`
  - `REDIS_PASSWORD`
  - `JWT_SECRET_KEY`
  - `ENCRYPTION_KEY`
- Define permissões 600 no `.env`

### ✅ Item 3: Estrutura de Diretórios
- Cria estrutura: `~/projeto/sky-poc-infra`, `sky-poc-backend`, etc.
- Valida que todos os diretórios existem
- Valida que Docker Compose paths estão corretos

### ✅ Item 4: Pré-requisitos
- Valida Docker instalado e rodando
- Valida Docker Compose instalado
- Valida Git instalado
- Valida permissões Docker (sudo docker funciona)

### ✅ Item 7: Subida dos Containers
- Para containers existentes
- Faz build e sobe containers: `docker compose up -d --build`
- Mostra status dos containers

### ✅ Item 8: Health Check
- Verifica Postgres: `pg_isready`
- Verifica Redis: `redis-cli ping`
- Verifica Backend: `curl http://localhost:8000/health`
- Verifica Frontend e Proxy

## Interpretando os Resultados

### ✅ Sucesso
```
✅✅✅ Deploy local para VM concluído com sucesso!
```

**Próximo passo:** Configurar GitHub Actions (Fase 3)

### ❌ Erro
```
❌ Deploy concluído com X erro(s)
```

**Ação:** Verifique os logs e corrija os erros

## Comandos Úteis Após Deploy

### Ver Logs
```bash
ssh -i keys/azure/id_rsa azureuser@$VM_IP \
  'cd ~/projeto/sky-poc-infra && sudo docker compose logs'
```

### Ver Status dos Containers
```bash
ssh -i keys/azure/id_rsa azureuser@$VM_IP \
  'cd ~/projeto/sky-poc-infra && sudo docker compose ps'
```

### Ver Logs de um Container Específico
```bash
ssh -i keys/azure/id_rsa azureuser@$VM_IP \
  'cd ~/projeto/sky-poc-infra && sudo docker compose logs backend'
```

### Reiniciar Containers
```bash
ssh -i keys/azure/id_rsa azureuser@$VM_IP \
  'cd ~/projeto/sky-poc-infra && sudo docker compose restart'
```

### Parar Containers
```bash
ssh -i keys/azure/id_rsa azureuser@$VM_IP \
  'cd ~/projeto/sky-poc-infra && sudo docker compose down'
```

## Problemas Comuns

### Erro: "Não foi possível conectar à VM"
**Solução:**
- Verifique se VM está rodando: `az vm show -d -g <rg> -n <vm> --query powerState`
- Verifique IP: `az vm show -d -g <rg> -n <vm> --query publicIps`
- Verifique chave SSH: `ls -la keys/azure/id_rsa`

### Erro: "Docker não está rodando"
**Solução:**
```bash
ssh -i keys/azure/id_rsa azureuser@$VM_IP 'sudo systemctl start docker'
```

### Erro: "azureuser não consegue executar sudo docker"
**Solução:**
```bash
ssh -i keys/azure/id_rsa azureuser@$VM_IP \
  'sudo usermod -aG docker azureuser && newgrp docker'
```

### Erro: "Branch não encontrada"
**Solução:**
- Verifique se branch existe: `git ls-remote --heads origin`
- Use branch correta: `export BRANCH=main` ou `export BRANCH=staging`

### Erro: "Repositório não encontrado" (se privado)
**Solução:**
```bash
export GH_PAT=seu_token
./scripts/deploy-local-to-vm.sh
```

## Próximos Passos

Após deploy bem-sucedido:

1. **Testar Aplicação:**
   - Frontend: http://$VM_IP
   - API: http://$VM_IP/api/v1
   - Health: http://$VM_IP/api/v1/health

2. **Fase 3: GitHub Actions**
   - Configurar secrets no GitHub
   - Ativar workflow automático


