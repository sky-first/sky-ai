# [HOTFIX] Fix Terraform Lock File Inconsistency Error

## 🔥 Problema Crítico

Deploy falha com erro:
```
Error: Inconsistent dependency lock file

The given plan file was created with a different set of external dependency
selections than the current configuration.
```

**Impacto:**
- ❌ **TODOS** os deploys via CI/CD estão falhando
- ❌ Impossível aplicar mudanças de Terraform
- ❌ PR #256 (P0.1 Security Context) bloqueado

---

## 🎯 Causa Raiz

Workflow **NÃO inclui** `.terraform.lock.hcl` no artifact do Terraform plan.

**Resultado:**
1. Terraform Plan roda com lock file (versão X dos providers)
2. Artifact é criado **SEM** lock file
3. Terraform Apply baixa artifact e tenta usar plan
4. Apply detecta inconsistência → **ERRO**

---

## ✅ Solução Implementada

Adicionar `.terraform.lock.hcl` ao artifact do plan.

### Mudanças (2 linhas):

#### Linha 1312 - Artifact Preparation:
```diff
  cp -f tfplan "$ARTIFACT_DIR/tfplan"
  cp -f plan-output.txt "$ARTIFACT_DIR/plan-output.txt"
  cp -f backend.hcl "$ARTIFACT_DIR/backend.hcl"
+ cp -f .terraform.lock.hcl "$ARTIFACT_DIR/.terraform.lock.hcl"  # FIX: Include lock file for consistency
  cp -rf .terraform "$ARTIFACT_DIR/.terraform"
```

#### Linha 1323 - Artifact Upload:
```diff
  path: |
    _tfplan_artifact/tfplan
    _tfplan_artifact/plan-output.txt
    _tfplan_artifact/backend.hcl
+   _tfplan_artifact/.terraform.lock.hcl
    _tfplan_artifact/.terraform
```

---

## 🧪 Como Testar

### 1. Merge este PR
```bash
# Merge para staging
```

### 2. Fazer um deploy de teste
```bash
# Fazer qualquer mudança em infra/ e push para staging
# Ou re-run do PR #256
```

### 3. Validar que funciona
```bash
# Verificar que "Terraform Apply" passa
# Verificar logs: "Acquiring state lock... Releasing state lock..."
# Sem erro "Inconsistent dependency lock file"
```

---

## 📊 Impacto da Mudança

### Positivo:
- ✅ Corrige **100%** dos deploys falhando
- ✅ Desbloqueia PR #256 (P0.1 Security Context)
- ✅ Garante consistência entre plan e apply
- ✅ Mudança **mínima** (2 linhas)

### Risco:
- ⚠️ **Muito baixo** - apenas adiciona arquivo ao artifact
- ⚠️ Não muda lógica do Terraform
- ⚠️ Não muda providers ou versões

---

## 🔗 Links Relacionados

- **Issue:** Deploy failures com "Inconsistent dependency lock file"
- **Documentação:** `docs/troubleshooting/terraform-lock-file-error.md`
- **PR Bloqueado:** #256 (P0.1 Security Context)

---

## ✅ Checklist

- [x] Mudança implementada (2 linhas)
- [x] Commit com conventional commits
- [x] Documentação criada
- [ ] Merge aprovado
- [ ] Deploy testado
- [ ] PR #256 desbloqueado

---

**Urgência:** 🔥 **CRÍTICA** - Bloqueia todos os deploys  
**Complexidade:** ✅ **BAIXA** - 2 linhas adicionadas  
**Risco:** ✅ **MUITO BAIXO** - Apenas adiciona arquivo ao artifact
