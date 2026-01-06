# ✅ CORREÇÕES APLICADAS

## 🔧 Erro Corrigido: `TFVARS_FILE: unbound variable`

### Problema
O script de validação de mudanças destrutivas estava usando `$TFVARS_FILE` antes de defini-la, causando erro com `set -euo pipefail`.

### Correção Aplicada

**Antes:**
```bash
RG_NAME=$(terraform output -raw resource_group_name 2>/dev/null || echo "")

if [ -z "$RG_NAME" ]; then
  TFVARS_FILE="${{ ... }}"  # Definido apenas dentro do if
  ...
fi

# Usado fora do if - ERRO se RG_NAME não estava vazio!
VM_NAME=$(grep "^vm_name" "$TFVARS_FILE" ...)  # ❌ Erro aqui
```

**Depois:**
```bash
# CRÍTICO: Definir TFVARS_FILE ANTES de usar
TFVARS_FILE="${{ needs.detect-environment.outputs.tfvars_file }}"

RG_NAME=$(terraform output -raw resource_group_name 2>/dev/null || echo "")

if [ -z "$RG_NAME" ] && [ -f "$TFVARS_FILE" ]; then
  RG_NAME=$(grep "^resource_group_name" "$TFVARS_FILE" ...)
fi

# Agora funciona sempre!
VM_NAME=$(grep "^vm_name" "$TFVARS_FILE" ...)  # ✅ OK
```

### Melhorias Adicionais

1. **Extração de VM_NAME melhorada**:
   - Tenta extrair do tfvars primeiro
   - Fallback para terraform output
   - Último fallback: nomes baseados no ambiente
     - staging → `skyfirstlabs-staging`
     - prod → `skyfirstlabs-prod`
     - poc-sky → `poc-sky`

2. **Diagnóstico melhorado**:
   - Mostra de onde tentou obter o Resource Group
   - Exibe valores do tfvars quando RG não é encontrado
   - Mensagens mais claras

---

## ⚠️ PROBLEMA RESTANTE (Não é bug no código)

O workflow ainda está tentando **destruir 14 recursos** porque:

### Causa
- Branch `staging` no GitHub ainda tem valores **ANTIGOS**:
  - `resource_group_name = "rg-ai-saas-staging"` ❌
  - `vm_name = "ai-saas-staging"` ❌

- Terraform quer criar recursos com nomes **NOVOS**:
  - `resource_group_name = "skyfirstlabs-poc"` ✅
  - `vm_name = "skyfirstlabs-staging"` ✅

- Como os nomes são diferentes, Terraform tenta:
  - Destruir recursos antigos
  - Criar recursos novos

### Solução
**Fazer merge das mudanças para a branch `staging`**:

```bash
# Opção 1: Criar Pull Request
# fix/containers-deploy-and-env-v2 → staging

# Opção 2: Cherry-pick (se tiver permissão)
git checkout staging
git cherry-pick 2580914  # commit: unificar Resource Group
git push origin staging
```

---

## ✅ Status

- [x] Erro `TFVARS_FILE: unbound variable` corrigido
- [x] Extração de VM_NAME melhorada
- [x] Diagnóstico melhorado
- [ ] Mudanças ainda precisam ser mergeadas para staging

---

**Commit**: `52c4fab` - fix: corrigir erro 'TFVARS_FILE: unbound variable'
**Próximo passo**: Fazer merge para staging para resolver o problema de destruição de recursos

