# Como Configurar GH_PAT para Repositórios Privados

## 1. Criar Personal Access Token no GitHub

1. Acesse: https://github.com/settings/tokens
2. Clique em **"Generate new token"** > **"Generate new token (classic)"**
3. Configure:
   - **Note**: `Deploy VM - sky-poc`
   - **Expiration**: Escolha uma data (ou "No expiration" para tokens de longa duração)
   - **Scopes**: Marque `repo` (acesso completo aos repositórios)
4. Clique em **"Generate token"**
5. **COPIE O TOKEN** (você só verá uma vez!)

## 2. Configurar Token Localmente

```bash
export GH_PAT=ghp_seu_token_aqui
```

Para tornar permanente (adicionar ao `~/.zshrc` ou `~/.bashrc`):
```bash
echo 'export GH_PAT=ghp_seu_token_aqui' >> ~/.zshrc
source ~/.zshrc
```

## 3. Executar Deploy

```bash
cd ~/Documents/poc:deploy:sky/sky-poc-infra
export VM_IP=172.191.77.30
export BRANCH=staging
export SSH_KEY=~/.ssh/id_ed25519
export GH_PAT=ghp_seu_token_aqui  # Se ainda não estiver no .zshrc
./scripts/deploy-local-to-vm.sh
```

Ou use o script helper:
```bash
export GH_PAT=ghp_seu_token_aqui
./scripts/executar-deploy.sh
```

## Segurança

⚠️ **NUNCA** commite o token no Git!
- O token fica apenas na sua máquina local
- O script envia o token para a VM via SSH (criptografado)
- Na VM, o token é usado apenas para clonar repositórios


