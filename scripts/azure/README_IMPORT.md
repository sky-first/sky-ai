# Import Resource Group - Guia de Uso

Este guia explica como importar um Resource Group existente no Azure para o Terraform State.

## Problema

Quando um Resource Group já existe no Azure mas não está no Terraform State, o Terraform tenta criá-lo novamente, causando o erro:
```
Error: A resource with the ID already exists
```

## Soluções

### Opção 1: Via GitHub Actions (Recomendado)

Execute o workflow manual `Import Resource Group`:

1. Acesse o GitHub: **Actions** > **Import Resource Group (Manual)**
2. Clique em **Run workflow**
3. Selecione o ambiente (staging/prod/poc-sky)
4. Opcionalmente, informe o nome do Resource Group (deixe vazio para usar o padrão)
5. Clique em **Run workflow**

O workflow irá:
- ✅ Verificar se o Resource Group existe no Azure
- ✅ Verificar se já está importado
- ✅ Executar o import se necessário
- ✅ Validar o import
- ✅ Salvar no backend remoto do Terraform

### Opção 2: Via Script PowerShell (Local)

**Pré-requisitos:**
- Terraform instalado
- Azure CLI instalado e autenticado (`az login`)
- PowerShell 5.1 ou superior

**Executar:**
```powershell
# Navegar para o diretório do script
cd scripts\azure

# Executar import para staging
.\import_resource_group.ps1 -Environment staging

# Ou para outros ambientes
.\import_resource_group.ps1 -Environment prod
.\import_resource_group.ps1 -Environment poc-sky

# Com Subscription ID específico
.\import_resource_group.ps1 -Environment staging -SubscriptionId "seu-subscription-id"
```

### Opção 3: Manual (Terraform CLI)

Se preferir executar manualmente:

```bash
# 1. Navegar para diretório do Terraform
cd infra/azure

# 2. Inicializar Terraform
terraform init

# 3. Selecionar workspace
terraform workspace select staging

# 4. Obter Subscription ID
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

# 5. Executar import
terraform import \
  -var-file="terraform.tfvars.staging" \
  -var="subscription_id=${SUBSCRIPTION_ID}" \
  azurerm_resource_group.main \
  "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-ai-saas-staging"

# 6. Verificar
terraform state show azurerm_resource_group.main
terraform plan -var-file="terraform.tfvars.staging" -var="subscription_id=${SUBSCRIPTION_ID}"
```

## Verificação

Após o import, verifique:

1. **Estado do Terraform:**
   ```bash
   terraform state show azurerm_resource_group.main
   ```

2. **Plan não deve tentar criar:**
   ```bash
   terraform plan -var-file="terraform.tfvars.staging"
   ```
   O plan não deve mostrar `azurerm_resource_group.main will be created`

3. **Pipeline deve funcionar:**
   Execute o pipeline de deploy normalmente. O step "Sync Existing Resources" deve detectar que o Resource Group já está importado.

## Troubleshooting

### Erro: "Resource Group não existe no Azure"
- Verifique se o Resource Group realmente existe: `az group show --name rg-ai-saas-staging`
- Verifique se está na subscription correta: `az account show`

### Erro: "Resource Group já está no estado"
- O Resource Group já foi importado anteriormente
- Execute `terraform state show azurerm_resource_group.main` para verificar
- Se necessário, remova do estado: `terraform state rm azurerm_resource_group.main` (cuidado!)

### Erro: "Workspace incorreto"
- Verifique o workspace: `terraform workspace show`
- Selecione o workspace correto: `terraform workspace select staging`

### Erro: "Backend não configurado"
- Para execução local, o backend pode não estar configurado
- Use o workflow do GitHub Actions para garantir que o estado seja salvo no backend remoto

## Próximos Passos

Após o import bem-sucedido:

1. ✅ O Resource Group está gerenciado pelo Terraform
2. ✅ O pipeline de deploy deve funcionar corretamente
3. ✅ Mudanças no Resource Group serão gerenciadas pelo Terraform

## Arquivos Relacionados

- Script PowerShell: `scripts/azure/import_resource_group.ps1`
- Workflow GitHub Actions: `.github/workflows/import-resource-group.yml`
- Configuração Terraform: `infra/azure/main.tf` (linha 26)

