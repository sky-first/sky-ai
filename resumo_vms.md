# Resumo das VMs do Azure

## 📊 Visão Geral

| VM | Resource Group | IP Público | Status | Tamanho | OS | Conteúdo |
|---|---|---|---|---|---|---|
| **ai-saas-vm** | AI-SAAS-RG | 172.191.77.30 | ✅ Rodando | Standard_B2s | Ubuntu 22.04 | ✅ Docker instalado<br>✅ Projeto poc-deploy |
| **ai-saas-dev** | RG-AI-SAAS-DEV | 4.246.185.242 | ✅ Rodando | Standard_B2s | Ubuntu 22.04 | ✅ Docker instalado<br>❌ Sem projeto |
| **ai-saas-staging** | RG-AI-SAAS-STAGING | 172.172.134.36 | ✅ Rodando | Standard_B2ms | Ubuntu 22.04 | ✅ Docker instalado<br>❌ Sem projeto |
| **poc-sky** | POC-SKY | 20.86.142.1 | ✅ Rodando | Standard_D2s_v3 | Ubuntu 24.04 | ❌ Docker não instalado<br>❌ Sem projeto |

---

## 🔍 Detalhes de Cada VM

### 1. ai-saas-vm (PRODUÇÃO)
- **IP:** 172.191.77.30
- **Tamanho:** Standard_B2s (2 vCPUs, 4GB RAM)
- **Status:** ✅ Rodando
- **Docker:** ✅ Instalado e rodando
- **Containers:** Nenhum rodando no momento
- **Projeto:** ✅ Tem `/home/azureuser/projeto/poc-deploy/`
  - Estrutura encontrada:
    - `docker/`
    - `scripts/`
    - `keys/`
    - `infra/`
- **Espaço em disco:** 26GB livres de 29GB (13% usado)
- **Portas:** Nenhuma porta específica escutando

**Conectar via SSH:**
```bash
ssh azureuser@172.191.77.30
```

---

### 2. ai-saas-dev (DESENVOLVIMENTO)
- **IP:** 4.246.185.242
- **Tamanho:** Standard_B2s (2 vCPUs, 4GB RAM)
- **Status:** ✅ Rodando
- **Docker:** ✅ Instalado e rodando
- **Containers:** Nenhum rodando no momento
- **Projeto:** ❌ Não tem diretório `~/projeto`
- **Espaço em disco:** 27GB livres de 29GB (9% usado)
- **Portas:** Nenhuma porta específica escutando

**Conectar via SSH:**
```bash
ssh azureuser@4.246.185.242
```

---

### 3. ai-saas-staging (STAGING)
- **IP:** 172.172.134.36
- **Tamanho:** Standard_B2ms (2 vCPUs, 8GB RAM) - **Maior que as outras!**
- **Status:** ✅ Rodando
- **Docker:** ✅ Instalado e rodando
- **Containers:** Nenhum rodando no momento
- **Projeto:** ❌ Não tem diretório `~/projeto`
- **Espaço em disco:** 27GB livres de 29GB (8% usado)
- **Portas:** Nenhuma porta específica escutando

**Conectar via SSH:**
```bash
ssh azureuser@172.172.134.36
```

---

### 4. poc-sky (POC SKY)
- **IP:** 20.86.142.1
- **Tamanho:** Standard_D2s_v3 (2 vCPUs, 8GB RAM) - **Mais potente!**
- **Status:** ✅ Rodando
- **Docker:** ❌ **NÃO instalado**
- **Containers:** N/A
- **Projeto:** ❌ Não tem diretório `~/projeto`
- **Espaço em disco:** 26GB livres de 29GB (8% usado)
- **Portas:** Nenhuma porta específica escutando

**Conectar via SSH:**
```bash
ssh azureuser@20.86.142.1
```

---

## 🛠️ Como Inspecionar uma VM

Use o script `inspect_vm.ps1`:

```powershell
# Exemplo: Inspecionar ai-saas-vm
.\inspect_vm.ps1 -ResourceGroup "AI-SAAS-RG" -VmName "ai-saas-vm"

# Exemplo: Inspecionar ai-saas-dev
.\inspect_vm.ps1 -ResourceGroup "RG-AI-SAAS-DEV" -VmName "ai-saas-dev"
```

---

## 📝 Observações

1. **Apenas `ai-saas-vm` tem o projeto deployado** - As outras VMs estão vazias/prontas para uso
2. **Nenhuma VM tem containers rodando** - Todas estão com Docker instalado mas sem serviços ativos
3. **`poc-sky` não tem Docker** - Precisa instalar se quiser usar containers
4. **`ai-saas-staging` e `poc-sky` têm mais RAM** (8GB vs 4GB) - Melhor para aplicações maiores

---

## 🚀 Próximos Passos Sugeridos

1. **Para usar `ai-saas-vm`:** Conectar e verificar o que está no projeto
2. **Para usar outras VMs:** Fazer deploy do projeto usando os scripts disponíveis
3. **Para `poc-sky`:** Instalar Docker primeiro antes de fazer deploy

