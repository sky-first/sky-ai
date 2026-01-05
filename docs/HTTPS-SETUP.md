# Configuração HTTPS - Guia Completo

## 📋 Resumo

Este documento descreve a solução DevOps implementada para habilitar HTTPS na VM, resolvendo o problema de `navigator.clipboard` que requer contexto seguro (HTTPS).

## 🎯 Objetivo

Habilitar HTTPS na VM para:
- ✅ Resolver erro `navigator.clipboard.writeText` (requer HTTPS)
- ✅ Melhorar segurança
- ✅ Permitir uso de APIs que exigem contexto seguro

## 📁 Arquivos Criados/Modificados

### Scripts Criados

1. **`scripts/azure/generate-self-signed-certs.sh`**
   - Gera certificados SSL auto-assinados para POC
   - Válidos por 365 dias
   - Suporta IP e domínio

2. **`scripts/azure/apply-nginx-config.sh`**
   - Detecta automaticamente se certificados existem
   - Aplica `nginx.conf.secure` (HTTPS) se certificados existirem
   - Fallback para `nginx.conf.http-only` se não existirem

3. **`scripts/azure/setup-https-vm.sh`**
   - Script automatizado para configurar HTTPS via SSH
   - Tenta múltiplas chaves SSH automaticamente
   - Executa os 3 passos: gerar certs → aplicar nginx → reiniciar proxy

4. **`scripts/azure/setup-https-vm-azure-cli.sh`**
   - Configura HTTPS usando Azure CLI `run-command` (sem SSH direto)
   - Útil quando Azure Bastion está habilitado
   - Cria scripts inline se não existirem na VM

5. **`scripts/azure/check-ssh-access.sh`**
   - Diagnostica acesso SSH
   - Verifica Azure Bastion
   - Verifica regras NSG
   - Sugere alternativas

6. **`scripts/azure/test-https-setup.sh`**
   - Valida toda a configuração HTTPS
   - Verifica scripts, Nginx, docker-compose
   - Útil antes do deploy

### Configurações Modificadas

1. **`docker/nginx/nginx.conf.secure`**
   - Configuração HTTPS completa
   - Redirect HTTP → HTTPS
   - DNS dinâmico (resolver + variáveis)
   - Headers de segurança (HSTS, CSP, etc.)
   - CORS configurado

2. **`docker-compose.yml`**
   - ✅ Já tinha porta 443 mapeada
   - ✅ Já tinha volume `./certs:/etc/nginx/certs:ro`

## 🚀 Como Usar

### Opção 1: Azure CLI (Recomendado quando SSH está bloqueado)

```bash
# 1. Login no Azure CLI
az login

# 2. Executar script
cd /Users/thedatafirst/Documents/poc-deploy-sky/sky-poc-infra
bash scripts/azure/setup-https-vm-azure-cli.sh 20.86.142.1
```

### Opção 2: SSH Direto (se disponível)

```bash
# Executar script
cd /Users/thedatafirst/Documents/poc-deploy-sky/sky-poc-infra
bash scripts/azure/setup-https-vm.sh 20.86.142.1
```

### Opção 3: Manual na VM

```bash
# Na VM (via Bastion ou SSH)
cd /home/azureuser/projeto/sky-poc-infra

# 1. Gerar certificados
bash scripts/azure/generate-self-signed-certs.sh . 20.86.142.1

# 2. Aplicar configuração Nginx
bash scripts/azure/apply-nginx-config.sh .

# 3. Reiniciar proxy
docker compose restart proxy
```

## ✅ Validação

Antes do deploy, execute o teste de validação:

```bash
bash scripts/azure/test-https-setup.sh
```

Este script verifica:
- ✅ Todos os scripts existem e têm sintaxe correta
- ✅ Configurações Nginx estão corretas
- ✅ docker-compose.yml está configurado
- ✅ Dependências estão disponíveis

## 🔍 Verificação Pós-Deploy

Após configurar HTTPS, verifique:

```bash
# 1. Verificar certificados foram gerados
ls -la certs/

# 2. Verificar nginx.conf foi atualizado
grep -i "ssl_certificate" docker/nginx/nginx.conf

# 3. Testar HTTPS
curl -k https://20.86.142.1/health

# 4. Verificar redirect HTTP->HTTPS
curl -I http://20.86.142.1
```

## ⚠️ Notas Importantes

1. **Certificados Auto-assinados**
   - Geram aviso no navegador (normal em POC)
   - Para produção, use Let's Encrypt ou certificados válidos

2. **Azure Bastion**
   - Se `enable_bastion = true`, SSH direto (porta 22) está bloqueado
   - Use `setup-https-vm-azure-cli.sh` ou Azure Portal/Bastion

3. **DNS Dinâmico**
   - Todas as configurações Nginx usam `resolver 127.0.0.11`
   - Evita erro 502 após recriação de containers

## 📊 Status dos Testes

Execução do `test-https-setup.sh`:
- ✅ 14/14 verificações passaram
- ⚠️  1 aviso (Azure CLI não logado - normal)

## 🔗 Referências

- Branch: `feat/https-ssl-support`
- Commits: 5 commits relacionados
- Arquivos: 6 scripts + 1 config Nginx atualizada

