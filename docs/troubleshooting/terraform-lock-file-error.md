# 🔍 Resumo Executivo - Falha do Terraform CI/CD

**Data:** 2026-02-12 23:45 UTC  
**Erro:** `Inconsistent dependency lock file`  
**Workflow:** Deploy Infrastructure (Merge PR #256)  
**Status:** ❌ FALHOU na etapa "Terraform Apply"

---

## ❌ O Que Aconteceu

### Erro Completo:
```
Error: Inconsistent dependency lock file

The given plan file was created with a different set of external dependency
selections than the current configuration. A saved plan can be applied only
to the same configuration it was created from.

Create a new plan from the updated configuration.
```

### Contexto:
- **Etapa 1 (Terraform Plan):** ✅ Passou (gerou `tfplan` com sucesso)
- **Etapa 2 (Terraform Apply):** ❌ Falhou ao tentar aplicar o `tfplan`

---

## 🎯 Causa Raiz

### Problema Identificado:

O workflow **NÃO está incluindo** `.terraform.lock.hcl` no artifact do plan.

#### Linha 1316-1324 do `deploy.yml`:
```yaml
- name: Upload Plan Artifact
  uses: actions/upload-artifact@v4
  with:
    name: tfplan-${{ needs.detect-environment.outputs.environment }}-${{ github.sha }}
    path: |
      _tfplan_artifact/tfplan
      _tfplan_artifact/plan-output.txt
      _tfplan_artifact/backend.hcl
      _tfplan_artifact/.terraform
    # ❌ FALTANDO: .terraform.lock.hcl
```

### Por Que Isso Causa o Erro:

1. **Terraform Plan** roda com `.terraform.lock.hcl` (versão X dos providers)
2. Artifact é criado **SEM** `.terraform.lock.hcl`
3. **Terraform Apply** baixa o artifact
4. **Terraform Apply** tenta usar o plan, mas:
   - Plan foi criado com versão X
   - Apply está usando versão Y (ou nenhum lock)
   - Terraform detecta inconsistência → **ERRO**

---

## 🔧 Soluções

### ✅ Solução 1: Re-run do Workflow (IMEDIATO - 5 minutos)

**Ação:**
1. Ir para GitHub Actions: https://github.com/sky-first/sky-poc-infra/actions
2. Encontrar o workflow falhado (PR #256)
3. Clicar em **"Re-run jobs"**

**Por que funciona:**
- Re-run executa plan + apply na **mesma** execução
- Usa o **mesmo** `.terraform.lock.hcl` em ambas as etapas

**Tempo:** 5-8 minutos

---

### ✅ Solução 2: Corrigir o Workflow (PERMANENTE - 10 minutos)

**Ação:** Adicionar `.terraform.lock.hcl` ao artifact.

#### Mudança Necessária:

```diff
# Linha 1304-1314 do deploy.yml
- name: Prepare Plan Artifact (stable paths)
  run: |
    set -euo pipefail
    ARTIFACT_DIR="${GITHUB_WORKSPACE}/_tfplan_artifact"
    mkdir -p "$ARTIFACT_DIR"
    cp -f tfplan "$ARTIFACT_DIR/tfplan"
    cp -f plan-output.txt "$ARTIFACT_DIR/plan-output.txt"
    cp -f backend.hcl "$ARTIFACT_DIR/backend.hcl"
+   cp -f .terraform.lock.hcl "$ARTIFACT_DIR/.terraform.lock.hcl"  # ← ADICIONAR
    cp -rf .terraform "$ARTIFACT_DIR/.terraform"
    echo "Artifact preparado em: $ARTIFACT_DIR"
    ls -la "$ARTIFACT_DIR"
```

```diff
# Linha 1316-1324 do deploy.yml
- name: Upload Plan Artifact
  uses: actions/upload-artifact@v4
  with:
    name: tfplan-${{ needs.detect-environment.outputs.environment }}-${{ github.sha }}
    path: |
      _tfplan_artifact/tfplan
      _tfplan_artifact/plan-output.txt
      _tfplan_artifact/backend.hcl
+     _tfplan_artifact/.terraform.lock.hcl  # ← ADICIONAR
      _tfplan_artifact/.terraform
```

**Tempo:** 10 minutos (implementar + testar)

---

### ✅ Solução 3: Commit do Lock File Atualizado (ALTERNATIVA)

**Ação:** Garantir que `.terraform.lock.hcl` está commitado e atualizado.

```bash
cd infra/aks
terraform providers lock \
  -platform=linux_amd64 \
  -platform=darwin_amd64 \
  -platform=darwin_arm64

git add .terraform.lock.hcl
git commit -m "chore(terraform): update provider lock file"
git push
```

**Por que funciona:**
- Garante que o lock file está versionado
- Ambas as etapas (plan + apply) usam o mesmo lock

**Tempo:** 5 minutos

---

## 📊 Impacto

### Impacto Atual:
- ❌ Deploy do PR #256 **FALHOU**
- ❌ Mudanças de infra **NÃO** foram aplicadas
- ⚠️ Staging pode estar **desatualizado** (dependendo do que estava no PR)

### Impacto se Não Corrigir:
- ❌ **TODOS** os próximos deploys vão falhar da mesma forma
- ❌ Impossível aplicar mudanças de Terraform via CI/CD
- ❌ Necessário aplicar manualmente (não recomendado)

---

## 🛡️ Prevenção Futura

### 1. Adicionar Validação no Workflow

```yaml
- name: Validate Lock File in Artifact
  run: |
    if [ ! -f "_tfplan_artifact/.terraform.lock.hcl" ]; then
      echo "❌ ERRO: .terraform.lock.hcl não encontrado no artifact"
      exit 1
    fi
    echo "✅ Lock file presente no artifact"
```

### 2. Adicionar ao Checklist de PR

```markdown
## Terraform Changes Checklist
- [ ] `.terraform.lock.hcl` está commitado
- [ ] `terraform fmt` executado
- [ ] `terraform validate` passou
```

### 3. Adicionar Pre-commit Hook

```bash
# .git/hooks/pre-commit
if git diff --cached --name-only | grep -q "infra/.*\.tf$"; then
  if ! git diff --cached --name-only | grep -q ".terraform.lock.hcl"; then
    echo "⚠️  Mudanças em .tf detectadas mas .terraform.lock.hcl não foi atualizado"
    echo "Execute: cd infra/aks && terraform providers lock"
    exit 1
  fi
fi
```

---

## 📋 Próximos Passos Recomendados

### Imediato (AGORA):
1. ✅ **Re-run do workflow** (solução mais rápida)
2. ⏳ Aguardar deploy completar (~8 minutos)
3. ✅ Validar que staging está OK

### Curto Prazo (Hoje):
1. ✅ Implementar **Solução 2** (corrigir workflow)
2. ✅ Testar em branch de teste
3. ✅ Fazer PR para corrigir o workflow

### Médio Prazo (Esta Semana):
1. ✅ Adicionar validação no workflow
2. ✅ Adicionar checklist de PR
3. ✅ Documentar processo de Terraform

---

## 🔗 Links Relacionados

- **Workflow Falhado:** https://github.com/sky-first/sky-poc-infra/actions (PR #256)
- **Documentação Terraform Lock:** https://developer.hashicorp.com/terraform/language/files/dependency-lock
- **GitHub Actions Artifacts:** https://docs.github.com/en/actions/using-workflows/storing-workflow-data-as-artifacts

---

## ✅ Resumo para Stakeholders

**Problema:** Deploy falhou por inconsistência no lock file do Terraform.  
**Causa:** Workflow não inclui `.terraform.lock.hcl` no artifact.  
**Solução:** Re-run do workflow (5 min) + correção permanente (10 min).  
**Impacto:** Zero downtime (deploy não foi aplicado).  
**Prevenção:** Correção no workflow + validações adicionais.

**Status:** ⏳ Aguardando re-run do workflow
