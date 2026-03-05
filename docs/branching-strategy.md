# Estratégia de Branching - Sky-First Infra

## 🚨 Regra Fundamental (Não Negociável)

**`staging` é a Fonte da Verdade durante a fase atual de desenvolvimento.**

A `main` está desatualizada e **só receberá merges depois que a `staging` estiver 100% validada e estável em ambiente real.**

---

## Fluxo Obrigatório de PR

```
feature/fix branch ──► staging (Source of Truth)
                                │
                          (validação completa)
                                │
                              main (apenas promoção final)
```

### ✅ Certo
```bash
# Sempre apontando para staging
gh pr create --base staging --head fix/minha-feature
```

### ❌ Errado (PROIBIDO)
```bash
# Nunca abrir PR diretamente para main
gh pr create --base main --head fix/minha-feature
```

---

## Nomenclatura de Branches

| Tipo | Padrão | Exemplo |
|------|--------|---------|
| Correção de bug | `fix/ID-descricao` | `fix/DO2025-500-eso-identity` |
| Nova funcionalidade | `feature/ID-descricao` | `feature/DO2025-123-new-cluster` |
| Hotfix urgent (prod) | `hotfix/ID-descricao` | `hotfix/DO2025-999-critical` |

---

## Regras de Proteção de Branch

- `main` → Protegida. Só recebe merges de `staging` após validação completa.
- `staging` → Protegida. Recebe merges de `feature/*` e `fix/*` após CI verde.
- `feature/*` / `fix/*` → Branches de trabalho. Nunca vivem mais de 72h sem merge ou fechamento.

---

## Ciclo de Vida de uma Correção

1. `git checkout staging && git pull`
2. `git checkout -b fix/ID-descricao`
3. Implementar e testar localmente
4. `git push origin fix/ID-descricao`
5. `gh pr create --base staging` → CI deve ser verde
6. Review + Merge para `staging`
7. ArgoCD sincroniza e valida em ambiente real
8. **Somente após validação:** abrir PR `staging → main`
