# Boas Práticas DevOps - Deploy

## Princípios Aplicados

### 1. **Fail Fast** (Falhar Rápido)
- ✅ Validar build **antes** de fazer deploy
- ✅ Validar Docker Compose antes de subir containers
- ✅ Validar estrutura de diretórios antes de clonar repositórios

### 2. **Separação de Responsabilidades**
- ✅ Scripts específicos para cada tarefa:
  - `validate-build.sh` - Valida build antes do deploy
  - `test-local-deploy.sh` - Valida ambiente local
  - `deploy-local-to-vm.sh` - Executa deploy
  - `health_check.sh` - Verifica saúde dos serviços

### 3. **Validação em Múltiplas Camadas**

#### Camada 1: Local (Pre-commit)
```bash
# Antes de commitar
./scripts/validate-build.sh
```

#### Camada 2: CI/CD (GitHub Actions)
- Valida build no CI antes de permitir merge
- Valida Docker Compose syntax
- Valida estrutura de diretórios

#### Camada 3: Pre-Deploy
- Valida build na VM antes de subir containers
- Valida .env e variáveis obrigatórias
- Valida caminhos do Docker Compose

### 4. **Logs e Observabilidade**
- ✅ Logs estruturados com cores e símbolos
- ✅ Logs salvos em arquivos temporários para análise
- ✅ Health checks após deploy

### 5. **Idempotência**
- ✅ Scripts podem ser executados múltiplas vezes
- ✅ Verificam estado antes de fazer mudanças
- ✅ Atualizam repositórios em vez de recriar

## Workflow Recomendado

### Desenvolvimento Local
```bash
# 1. Fazer mudanças no código
cd sky-poc-frontend
# ... fazer mudanças ...

# 2. Validar build localmente
npm run build

# 3. Validar tudo antes de commitar
cd ../sky-poc-infra
./scripts/validate-build.sh

# 4. Se tudo OK, commitar e fazer push
cd ../sky-poc-frontend
git add .
git commit -m "feat: nova feature"
git push origin staging
```

### Deploy Local para VM
```bash
# 1. Validar build antes de fazer deploy
cd sky-poc-infra
./scripts/validate-build.sh

# 2. Se validação OK, fazer deploy
export GH_PAT=seu_token
export VM_IP=172.191.77.30
export BRANCH=staging
./scripts/deploy-local-to-vm.sh
```

### CI/CD (GitHub Actions)
O workflow já valida:
- ✅ Docker Compose syntax
- ✅ Estrutura de diretórios
- ✅ Build do frontend (se configurado)

## Resolução de Problemas

### Build do Frontend Falha

**Sintoma**: `Error: Turbopack build failed`

**Causas Comuns**:
1. Erros de sintaxe no código
2. Arquivos muito grandes (>10k linhas)
3. Dependências faltando
4. Problemas de parsing do Turbopack

**Solução**:
```bash
# 1. Validar build localmente
cd sky-poc-frontend
npm run build

# 2. Se falhar, verificar erros
npm run build 2>&1 | grep -A 20 "error\|Error\|ERROR"

# 3. Corrigir erros e validar novamente
./scripts/validate-build.sh

# 4. Só depois fazer deploy
./scripts/deploy-local-to-vm.sh
```

### Arquivo Muito Grande

**Problema**: Arquivo com >10k linhas causa problemas de parsing

**Solução** (Boas Práticas):
1. **Dividir em componentes menores**
   ```bash
   # Exemplo: settings-sections.tsx (10k linhas)
   # Dividir em:
   # - settings-sections-data-catalog.tsx
   # - settings-sections-permissions.tsx
   # - settings-sections-users.tsx
   ```

2. **Usar Lazy Loading**
   ```typescript
   const DataCatalogSection = lazy(() => import('./settings-sections-data-catalog'))
   ```

3. **Code Splitting**
   - Next.js faz isso automaticamente
   - Verificar se está configurado corretamente

## Checklist de Deploy

Antes de fazer deploy, verifique:

- [ ] Build do frontend funciona localmente
- [ ] Build do backend funciona localmente (se aplicável)
- [ ] Docker Compose syntax está válido
- [ ] .env está configurado com todas as variáveis
- [ ] Repositórios estão atualizados na branch correta
- [ ] Validação local passou: `./scripts/validate-build.sh`
- [ ] Health checks estão configurados no docker-compose.yml

## Monitoramento Pós-Deploy

Após deploy bem-sucedido:

```bash
# 1. Verificar health checks
ssh azureuser@VM_IP "cd ~/projeto/sky-poc-infra && ./scripts/health_check.sh"

# 2. Verificar logs dos containers
ssh azureuser@VM_IP "cd ~/projeto/sky-poc-infra && docker compose logs --tail=50"

# 3. Verificar status dos containers
ssh azureuser@VM_IP "cd ~/projeto/sky-poc-infra && docker compose ps"
```

## Referências

- [12 Factor App](https://12factor.net/)
- [DevOps Best Practices](https://www.atlassian.com/devops)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Next.js Production Checklist](https://nextjs.org/docs/deployment#production-checklist)


