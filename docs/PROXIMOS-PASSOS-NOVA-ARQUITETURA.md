# Próximos Passos - Nova Arquitetura

## 📋 Resumo da Nova Arquitetura

- **Resource Group único**: `skyfirstlabs-poc` (compartilhado entre staging e prod)
- **VM Staging**: `skyfirstlabs-staging` (workspace: `staging`)
- **VM Prod**: `skyfirstlabs-prod` (workspace: `prod`)
- **Cada ambiente mantém recursos únicos**: VNet, NSG, Public IP (nomes diferentes por ambiente)

---

## 🎯 Cenário 1: Primeiro Deploy (Nenhuma VM Existe)

Se você ainda não tem VMs criadas, siga estes passos:

### Passo 1: Verificar Estado Atual

```bash
# Verificar se o Resource Group já existe
az group show --name skyfirstlabs-poc --query "{name:name, location:location}" -o table

# Verificar VMs existentes
az vm list --query "[?resourceGroup=='skyfirstlabs-poc'].{Name:name, ResourceGroup:resourceGroup}" -o table
```

**Se o Resource Group não existir**: Será criado automaticamente no primeiro deploy.

### Passo 2: Fazer Commit das Mudanças

```bash
# Verificar mudanças
git status

# Adicionar arquivos modificados
git add infra/azure/terraform.tfvars.staging
git add infra/azure/terraform.tfvars.prod
git add infra/azure/main.tf
git add scripts/azure/import_resource_group.ps1

# Commit
git commit -m "feat: unificar Resource Group skyfirstlabs-poc para staging e prod"

# Push para staging (criará VM staging)
git push origin staging
```

### Passo 3: Monitorar Deploy Staging

1. Acesse: https://github.com/sky-first/sky-poc-infra/actions
2. Abra o workflow "Deploy Infrastructure" em execução
3. Verifique:
   - ✅ Workspace `staging` selecionado
   - ✅ Resource Group `skyfirstlabs-poc` será criado
   - ✅ VM `skyfirstlabs-staging` será criada
   - ✅ Terraform Apply concluído com sucesso

### Passo 4: Deploy Prod (Após Staging)

```bash
# Push para main (criará VM prod)
git push origin main
```

**Importante**: O Resource Group `skyfirstlabs-poc` já existirá (criado pelo staging), então o Terraform apenas referenciará o existente.

---

## 🔄 Cenário 2: Migrar VMs Existentes

Se você já tem VMs nos Resource Groups antigos (`rg-ai-saas-staging`, `rg-ai-saas-prod`), você tem duas opções:

### Opção A: Mover VMs para o Novo Resource Group (Recomendado)

```bash
# 1. Verificar VMs existentes
az vm list --query "[].{Name:name, ResourceGroup:resourceGroup}" -o table

# 2. Mover VM staging (se existir)
az vm move \
  --resource-group rg-ai-saas-staging \
  --name ai-saas-staging \
  --destination-group skyfirstlabs-poc \
  --new-name skyfirstlabs-staging

# 3. Mover VM prod (se existir)
az vm move \
  --resource-group rg-ai-saas-prod \
  --name ai-saas-vm \
  --destination-group skyfirstlabs-poc \
  --new-name skyfirstlabs-prod
```

**⚠️ ATENÇÃO**: Mover VMs pode causar downtime. Faça backup antes!

### Opção B: Importar VMs Existentes no Terraform

Se as VMs já estão no Resource Group correto mas com nomes diferentes:

```bash
cd infra/azure

# 1. Inicializar Terraform
terraform init

# 2. Selecionar workspace staging
terraform workspace select staging

# 3. Importar VM existente (se necessário)
terraform import \
  -var-file=terraform.tfvars.staging \
  azurerm_linux_virtual_machine.main \
  /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/skyfirstlabs-poc/providers/Microsoft.Compute/virtualMachines/<VM_NAME_EXISTENTE>

# 4. Verificar plan
terraform plan -var-file=terraform.tfvars.staging
```

---

## ✅ Verificação Pós-Deploy

### 1. Verificar Resource Group e VMs

```bash
# Listar recursos no Resource Group
az resource list \
  --resource-group skyfirstlabs-poc \
  --query "[].{Name:name, Type:type}" \
  -o table

# Verificar VMs
az vm list \
  --resource-group skyfirstlabs-poc \
  --query "[].{Name:name, Status:powerState, IP:publicIps}" \
  -o table
```

**Resultado esperado**:
- ✅ Resource Group: `skyfirstlabs-poc`
- ✅ VM: `skyfirstlabs-staging` (status: VM running)
- ✅ VM: `skyfirstlabs-prod` (status: VM running)

### 2. Verificar Workspaces do Terraform

```bash
cd infra/azure

# Listar workspaces
terraform workspace list

# Verificar workspace staging
terraform workspace select staging
terraform state list | grep azurerm_linux_virtual_machine

# Verificar workspace prod
terraform workspace select prod
terraform state list | grep azurerm_linux_virtual_machine
```

**Resultado esperado**:
- ✅ Workspace `staging` gerencia apenas `skyfirstlabs-staging`
- ✅ Workspace `prod` gerencia apenas `skyfirstlabs-prod`

### 3. Testar Deploy Automático

```bash
# Fazer uma mudança pequena (ex: adicionar tag)
# Editar terraform.tfvars.staging e fazer commit

git add infra/azure/terraform.tfvars.staging
git commit -m "test: verificar deploy automático staging"
git push origin staging

# Verificar que apenas a VM staging foi atualizada
# Repetir para prod
git push origin main
```

---

## 🚨 Troubleshooting

### Problema: "Resource Group já existe"

**Sintoma**: Terraform tenta criar Resource Group que já existe.

**Solução**:
```bash
cd infra/azure
terraform workspace select staging  # ou prod

# Importar Resource Group existente
terraform import \
  -var-file=terraform.tfvars.staging \
  azurerm_resource_group.main \
  /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/skyfirstlabs-poc
```

### Problema: "VM com nome diferente já existe"

**Sintoma**: VM antiga (`ai-saas-staging`) existe mas Terraform quer criar nova (`skyfirstlabs-staging`).

**Solução**:
1. Renomear VM existente:
```bash
az vm rename \
  --resource-group skyfirstlabs-poc \
  --name ai-saas-staging \
  --new-name skyfirstlabs-staging
```

2. Ou importar VM existente com nome antigo e depois renomear via Terraform.

### Problema: "Conflito de VNet/NSG"

**Sintoma**: Erro ao criar VNet ou NSG porque já existe.

**Causa**: Ambientes anteriores criaram recursos com nomes conflitantes.

**Solução**: Os nomes agora incluem `${var.environment}`, então não deve haver conflito. Se houver:
```bash
# Verificar recursos existentes
az network vnet list --resource-group skyfirstlabs-poc -o table
az network nsg list --resource-group skyfirstlabs-poc -o table

# Remover recursos antigos se necessário (CUIDADO!)
```

### Problema: "Workspace não encontrado"

**Sintoma**: Terraform não encontra workspace.

**Solução**:
```bash
cd infra/azure
terraform init
terraform workspace new staging  # se não existir
terraform workspace new prod      # se não existir
```

---

## 📝 Checklist Final

Antes de considerar completo, verifique:

- [ ] Resource Group `skyfirstlabs-poc` existe no Azure
- [ ] VM `skyfirstlabs-staging` existe e está rodando
- [ ] VM `skyfirstlabs-prod` existe e está rodando
- [ ] Workspace `staging` gerencia apenas recursos do staging
- [ ] Workspace `prod` gerencia apenas recursos do prod
- [ ] Deploy automático funciona (push para staging atualiza apenas staging)
- [ ] Deploy automático funciona (push para main atualiza apenas prod)
- [ ] Ambas as VMs têm IPs públicos diferentes
- [ ] Ambas as VMs podem ser acessadas via SSH/Bastion

---

## 🎉 Próximos Passos Após Validação

1. **Monitorar custos**: Verificar se o Resource Group compartilhado está otimizando custos
2. **Documentar IPs**: Anotar IPs públicos das VMs para acesso
3. **Configurar alertas**: Verificar se alertas do Azure Monitor estão funcionando
4. **Testar deploys**: Fazer deploys de teste em staging antes de prod

---

## 📞 Suporte

Se encontrar problemas:

1. Verificar logs do GitHub Actions
2. Verificar estado do Terraform: `terraform show`
3. Verificar recursos no Azure Portal
4. Consultar documentação: `infra/azure/README.md`

---

**Última atualização**: 2026-01-XX
**Autor**: Equipe DevOps

