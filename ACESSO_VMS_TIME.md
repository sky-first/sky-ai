# 🔐 Acesso às VMs - Guia para o Time

Este documento contém todas as informações necessárias para acessar as VMs do Azure.

---

## 📦 O que você precisa

1. **Chave SSH privada** - Você receberá via canal seguro
2. **Cliente SSH instalado** (já vem no Windows 10+, Linux e Mac)
3. **Acesso à internet**

**⚠️ IMPORTANTE:** Você **NÃO precisa** ter conta no Azure nem fazer login para acessar as VMs via SSH. O acesso é direto usando a chave SSH.

---

## 🔑 Chaves SSH Disponíveis

Cada VM tem sua própria chave SSH. Você receberá as chaves privadas via canal seguro.

| VM | Ambiente | Chave SSH |
|---|---|---|
| **ai-saas-vm** | Produção | `keys/azure/team/id_rsa_prod` |
| **ai-saas-dev** | Desenvolvimento | `keys/azure/team/id_rsa_dev` |
| **ai-saas-staging** | Staging | `keys/azure/team/id_rsa_staging` |
| **poc-sky** | POC | `keys/azure/team/id_rsa_poc` |

---

## 🚀 Como Conectar

### Passo 1: Baixar e Configurar a Chave SSH

**Windows PowerShell:**
```powershell
# 1. Criar diretório se não existir
New-Item -ItemType Directory -Force -Path keys\azure\team

# 2. Baixar a chave privada (você receberá via canal seguro)
# Coloque o arquivo em: keys\azure\team\id_rsa_prod (ou dev, staging, poc)

# 3. Configurar permissões
icacls keys\azure\team\id_rsa_prod /inheritance:r
icacls keys\azure\team\id_rsa_prod /grant:r "$env:USERNAME:R"
```

**Linux/Mac:**
```bash
# 1. Criar diretório se não existir
mkdir -p keys/azure/team

# 2. Baixar a chave privada (você receberá via canal seguro)
# Coloque o arquivo em: keys/azure/team/id_rsa_prod (ou dev, staging, poc)

# 3. Configurar permissões
chmod 600 keys/azure/team/id_rsa_prod
```

### Passo 2: Conectar na VM

**⚠️ NOTA:** Você **NÃO precisa** de conta Azure nem fazer `az login` para acessar via SSH. O acesso é direto usando a chave SSH.

**Opção A: SSH Direto (Mais Simples - Recomendado)**

Não precisa de scripts nem Azure CLI, apenas SSH:

**Produção (ai-saas-vm):**
```powershell
# Windows
ssh -i keys\azure\team\id_rsa_prod azureuser@172.191.77.30

# Linux/Mac
ssh -i keys/azure/team/id_rsa_prod azureuser@172.191.77.30
```

**Desenvolvimento (ai-saas-dev):**
```powershell
# Windows
ssh -i keys\azure\team\id_rsa_dev azureuser@4.246.185.242

# Linux/Mac
ssh -i keys/azure/team/id_rsa_dev azureuser@4.246.185.242
```

**Staging (ai-saas-staging):**
```powershell
# Windows
ssh -i keys\azure\team\id_rsa_staging azureuser@172.172.134.36

# Linux/Mac
ssh -i keys/azure/team/id_rsa_staging azureuser@172.172.134.36
```

**POC (poc-sky):**
```powershell
# Windows
ssh -i keys\azure\team\id_rsa_poc azureuser@20.86.142.1

# Linux/Mac
ssh -i keys/azure/team/id_rsa_poc azureuser@20.86.142.1
```

**Opção B: Usando o script automatizado (Opcional)**

Se você tiver Azure CLI instalado e autenticado, pode usar o script:

```powershell
# Windows PowerShell
.\ssh_vm.ps1 ai-saas-vm        # Produção
.\ssh_vm.ps1 ai-saas-dev        # Desenvolvimento
.\ssh_vm.ps1 ai-saas-staging    # Staging
.\ssh_vm.ps1 poc-sky            # POC
```

**Nota:** O script é apenas uma conveniência. O acesso SSH direto funciona sem Azure CLI.

---

## 📋 Resumo Rápido - Informações das VMs

| VM | IP Público | Usuário | Chave SSH |
|---|---|---|---|
| **Produção** | 172.191.77.30 | azureuser | `keys/azure/team/id_rsa_prod` |
| **Desenvolvimento** | 4.246.185.242 | azureuser | `keys/azure/team/id_rsa_dev` |
| **Staging** | 172.172.134.36 | azureuser | `keys/azure/team/id_rsa_staging` |
| **POC** | 20.86.142.1 | azureuser | `keys/azure/team/id_rsa_poc` |

---

## 🎯 Comandos Úteis Após Conectar

Uma vez conectado na VM:

```bash
# Ver containers Docker rodando
docker ps

# Ver todos os containers (incluindo parados)
docker ps -a

# Ver logs de um container
docker logs <nome-do-container>

# Verificar espaço em disco
df -h

# Ver processos rodando
ps aux

# Verificar portas em uso
sudo netstat -tlnp
# ou
sudo ss -tlnp

# Navegar para o projeto (se existir)
cd ~/projeto/poc-deploy

# Ver estrutura do projeto
ls -la
```

---

## ⚠️ Troubleshooting

### Problema: "Permission denied (publickey)"

**Solução:**
1. Verifique se a chave está no local correto
2. Verifique as permissões da chave:
   - **Windows:** `icacls keys\azure\team\id_rsa_prod`
   - **Linux/Mac:** `chmod 600 keys/azure/team/id_rsa_prod`
3. Verifique se está usando a chave correta para cada VM

### Problema: "Connection timeout"

**Solução:**
1. Verifique se a VM está rodando (peça ao administrador)
2. Verifique sua conexão com a internet
3. Verifique se o firewall não está bloqueando

### Problema: "No such file or directory" (chave não encontrada)

**Solução:**
1. Verifique o caminho da chave
2. Use caminho absoluto se necessário:
   - **Windows:** `C:\caminho\completo\keys\azure\team\id_rsa_prod`
   - **Linux/Mac:** `/caminho/completo/keys/azure/team/id_rsa_prod`

---

## 📞 Suporte

Se tiver problemas de acesso, entre em contato com o administrador da infraestrutura.

---

## ✅ Checklist de Setup

- [ ] Chaves SSH baixadas e colocadas em `keys/azure/team/`
- [ ] Permissões das chaves configuradas (`chmod 600` ou `icacls`)
- [ ] Teste de conexão bem-sucedido em pelo menos uma VM

**Nota:** Azure CLI é **opcional**. Você só precisa se quiser usar scripts de automação ou gerenciar recursos Azure.

---

## 🔐 Segurança

**IMPORTANTE:**
- ⚠️ **NUNCA** compartilhe as chaves privadas publicamente
- ⚠️ **NUNCA** commite chaves privadas no Git
- ✅ Mantenha as chaves em local seguro
- ✅ Use permissões corretas nas chaves (600)
- ✅ Reporte imediatamente se uma chave for comprometida

