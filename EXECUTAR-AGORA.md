# 🚀 EXECUTAR AGORA - Nova Arquitetura

## ✅ O que já foi feito

1. ✅ **Configuração atualizada**:
   - `terraform.tfvars.staging` → Resource Group: `skyfirstlabs-poc`, VM: `skyfirstlabs-staging`
   - `terraform.tfvars.prod` → Resource Group: `skyfirstlabs-poc`, VM: `skyfirstlabs-prod`
   - `main.tf` → Adicionado `lifecycle { ignore_changes = [tags] }` no Resource Group

2. ✅ **Scripts criados**:
   - `scripts/validate-new-architecture.sh` - Validação pré-deploy
   - `scripts/verify-deployment-complete.sh` - Verificação pós-deploy

3. ✅ **Commit realizado**: Todas as mudanças foram commitadas na branch atual

4. ✅ **Validação local**: Passou sem erros

---

## 🎯 PRÓXIMOS PASSOS (EXECUTAR AGORA)

### Passo 1: Validar Localmente (Opcional mas Recomendado)

```bash
# Executar validação
./scripts/validate-new-architecture.sh
```

### Passo 2: Fazer Push para GitHub

**Opção A: Se você quer fazer deploy de staging primeiro**

```bash
# Verificar branch atual
git branch --show-current

# Se estiver em uma branch de feature, fazer merge para staging
git checkout staging
git merge fix/containers-deploy-and-env-v2  # ou sua branch atual
git push origin staging
```

**Opção B: Se você quer fazer deploy direto para main (prod)**

```bash
git checkout main
git merge fix/containers-deploy-and-env-v2  # ou sua branch atual
git push origin main
```

**Opção C: Fazer push da branch atual e criar PR**

```bash
git push origin fix/containers-deploy-and-env-v2
# Depois criar Pull Request no GitHub para staging ou main
```

### Passo 3: Monitorar Deploy no GitHub Actions

1. Acesse: https://github.com/sky-first/sky-poc-infra/actions
2. Abra o workflow "Deploy Infrastructure" em execução
3. Verifique:
   - ✅ Workspace correto selecionado (staging ou prod)
   - ✅ Resource Group `skyfirstlabs-poc` será criado/referenciado
   - ✅ VM correta será criada/atualizada
   - ✅ Terraform Apply concluído com sucesso

### Passo 4: Verificar Deploy Completo

Após o deploy concluir, execute:

```bash
# Verificação completa
./scripts/verify-deployment-complete.sh
```

Este script verifica:
- ✅ Resource Group existe
- ✅ VMs existem e estão rodando
- ✅ IPs públicos configurados
- ✅ Recursos de rede (VNet, NSG, Public IPs)
- ✅ Conectividade HTTP básica

---

## 🔍 Verificação Manual Rápida

Se preferir verificar manualmente:

```bash
# 1. Verificar Resource Group
az group show --name skyfirstlabs-poc --query "{name:name, location:location}" -o table

# 2. Verificar VMs
az vm list --resource-group skyfirstlabs-poc \
  --query "[].{Name:name, Status:powerState, IP:publicIps}" \
  -o table

# 3. Verificar recursos
az resource list --resource-group skyfirstlabs-poc \
  --query "[].{Name:name, Type:type}" \
  -o table
```

---

## ⚠️ Se Encontrar Problemas

### Problema: Resource Group já existe mas Terraform tenta criar

**Solução**: O workflow do GitHub Actions tem um step "Sync Existing Resources" que deve importar automaticamente. Se falhar:

```bash
cd infra/azure
terraform workspace select staging  # ou prod
terraform import \
  -var-file=terraform.tfvars.staging \
  azurerm_resource_group.main \
  /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/skyfirstlabs-poc
```

### Problema: VM com nome antigo existe

**Solução**: Renomear ou importar:

```bash
# Renomear VM
az vm rename \
  --resource-group skyfirstlabs-poc \
  --name ai-saas-staging \
  --new-name skyfirstlabs-staging
```

### Problema: Deploy falha no GitHub Actions

**Solução**: 
1. Verificar logs do workflow
2. Verificar secrets do GitHub (AZURE_SUBSCRIPTION_ID, etc.)
3. Verificar se backend do Terraform está configurado

---

## 📋 Checklist Final

Após o deploy, verificar:

- [ ] Resource Group `skyfirstlabs-poc` existe no Azure
- [ ] VM `skyfirstlabs-staging` existe e está rodando (se deploy staging)
- [ ] VM `skyfirstlabs-prod` existe e está rodando (se deploy prod)
- [ ] Ambas as VMs têm IPs públicos diferentes
- [ ] Script `verify-deployment-complete.sh` passa sem erros
- [ ] Deploy automático funciona (push atualiza apenas a VM correta)

---

## 🎉 Quando Estiver Tudo Funcionando

1. **Documentar IPs**: Anotar IPs públicos das VMs
2. **Testar Acesso**: Conectar via SSH/Bastion
3. **Verificar Aplicações**: Testar frontend/backend nas VMs
4. **Monitorar Custos**: Verificar custos no Azure Portal

---

## 📞 Precisa de Ajuda?

- Ver documentação completa: `docs/PROXIMOS-PASSOS-NOVA-ARQUITETURA.md`
- Verificar logs do GitHub Actions
- Executar scripts de validação: `./scripts/validate-new-architecture.sh`

---

**Status Atual**: ✅ Configuração pronta, aguardando push e deploy
**Última atualização**: $(date)

