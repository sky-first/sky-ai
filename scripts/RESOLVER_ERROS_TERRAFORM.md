# Como Resolver os Erros do Terraform Apply

Este documento explica como resolver os dois erros que ocorreram no `terraform apply`:

1. **Action Group já existe mas não está no estado do Terraform**
2. **IP público em uso por NIC antiga (`ai-saas-nic` vs `ai-saas-nic-staging`)**

## ✅ Solução Automática (Recomendada)

**As mudanças no workflow já resolvem isso automaticamente!** 

Na próxima execução do GitHub Actions, o workflow vai:
- Importar o Action Group automaticamente se existir
- Detectar e desanexar IP público de NICs antigas antes de criar a nova NIC

Você só precisa executar o workflow novamente.

## 🔧 Solução Manual (Se necessário)

Se precisar resolver manualmente antes da próxima execução, siga estes passos:

### Pré-requisitos

```powershell
# Verificar se está autenticado
az account show

# Se não estiver autenticado
az login
```

### Passo 1: Importar Action Group

**Nota:** Isso precisa ser feito via Terraform, então você precisa ter o Terraform instalado ou executar via GitHub Actions.

```bash
# No GitHub Actions ou localmente com Terraform instalado
cd infra/azure

SUBSCRIPTION_ID="e1070cf9-7790-4f2d-b449-d4bf4bc21906"
RESOURCE_GROUP_NAME="rg-ai-saas-staging"
ACTION_GROUP_NAME="ai-saas-alerts-staging"
ACTION_GROUP_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP_NAME}/providers/Microsoft.Insights/actionGroups/${ACTION_GROUP_NAME}"

terraform import \
  -var-file="terraform.tfvars.staging" \
  -var="subscription_id=${SUBSCRIPTION_ID}" \
  azurerm_monitor_action_group.main "${ACTION_GROUP_ID}"
```

### Passo 2: Resolver Conflito de IP Público

**⚠️ ATENÇÃO:** A VM `ai-saas-staging` está usando a NIC antiga `ai-saas-nic`. 

**Opção A: Desanexar IP da NIC antiga (recomendado se a VM não estiver em uso crítico)**

```powershell
# Desanexar IP público da NIC antiga
az network nic ip-config update `
  --resource-group rg-ai-saas-staging `
  --nic-name ai-saas-nic `
  --name internal `
  --remove public-ip-address

# Verificar se foi desanexado
az network public-ip show `
  --resource-group rg-ai-saas-staging `
  --name ai-saas-public-ip-staging `
  --query "ipConfiguration.id" -o tsv
```

**Opção B: Se a VM estiver em produção/crítica**

Se a VM estiver em uso e você não pode desanexar o IP agora, você tem duas opções:

1. **Aguardar a próxima execução do workflow** - O workflow atualizado vai lidar com isso automaticamente
2. **Fazer uma manutenção programada:**
   - Parar a VM
   - Desanexar a NIC antiga
   - Anexar a nova NIC (que será criada pelo Terraform)
   - Iniciar a VM

### Passo 3: Verificar Estado

```powershell
# Listar NICs no resource group
az network nic list --resource-group rg-ai-saas-staging -o table

# Ver qual IP está associado a qual NIC
az network public-ip show `
  --resource-group rg-ai-saas-staging `
  --name ai-saas-public-ip-staging `
  --query "{Name:name, AssociatedNIC:ipConfiguration.id}" -o json
```

## 📋 Situação Atual Detectada

Executando os comandos de diagnóstico, encontramos:

```
✅ Action Group existe: ai-saas-alerts-staging
❌ Action Group NÃO está no estado do Terraform (precisa import)

✅ IP público existe: ai-saas-public-ip-staging  
⚠️  IP público está associado à NIC antiga: ai-saas-nic
   (Terraform quer criar: ai-saas-nic-staging)

⚠️  VM em execução: ai-saas-staging
   Usando NIC: ai-saas-nic (antiga)
```

## 🎯 Recomendação

**Para ambiente staging:** A solução mais simples é deixar o workflow atualizado resolver na próxima execução. O workflow vai:
1. Importar o Action Group
2. Detectar o conflito de IP
3. Tentar desanexar o IP da NIC antiga automaticamente
4. Criar/importar a nova NIC

Se o desanexo automático falhar (por exemplo, se a VM estiver usando a NIC), o workflow vai mostrar um aviso mas não vai falhar. Nesse caso, você pode fazer a correção manual seguindo a "Opção B" acima.

## 🚀 Próximos Passos

1. ✅ **Workflow já atualizado** - As correções estão no `.github/workflows/deploy.yml`
2. 🔄 **Execute o workflow novamente** - Na próxima execução, os problemas serão resolvidos automaticamente
3. 📊 **Monitore os logs** - O workflow vai mostrar mensagens informativas sobre o que está fazendo

