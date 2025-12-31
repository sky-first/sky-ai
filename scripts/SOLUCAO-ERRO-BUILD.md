# Solução para Erro de Build do Frontend

## Problema

O build do frontend está falhando com erro:
```
Error: Turbopack build failed with 1 errors:
./src/components/dashboard/settings-sections.tsx:8789:18
Unterminated regexp literal
```

## Causa Raiz

O arquivo `settings-sections.tsx` tem **10.982 linhas**, o que está causando problemas de parsing no **Turbopack** (bundler padrão do Next.js 16).

## Soluções

### Solução Temporária (Aplicada)

✅ **Usar Webpack em vez de Turbopack para build**

Atualizado `package.json`:
```json
"build": "next build --webpack"
```

**Por quê funciona:**
- Webpack é mais estável para arquivos grandes
- Turbopack ainda está em desenvolvimento e tem limitações com arquivos muito grandes

**Como testar:**
```bash
cd sky-poc-frontend
npm run build
```

### Solução Permanente (Recomendada)

🔧 **Dividir arquivo grande em componentes menores**

O arquivo `settings-sections.tsx` (10.982 linhas) deve ser dividido em:

```
src/components/dashboard/settings-sections/
├── index.tsx                    # Exportações principais
├── data-catalog-section.tsx     # ~2000 linhas
├── permissions-section.tsx       # ~2000 linhas
├── spaces-section.tsx           # ~2000 linhas
├── crews-section.tsx            # ~2000 linhas
├── users-section.tsx            # ~2000 linhas
└── shared/                      # Componentes compartilhados
    ├── actions-dropdown.tsx
    ├── delete-modal.tsx
    └── ...
```

**Benefícios:**
- ✅ Melhor performance de build
- ✅ Melhor manutenibilidade
- ✅ Code splitting automático
- ✅ Melhor experiência de desenvolvimento

## Próximos Passos

1. ✅ **Imediato**: Build com Webpack (já aplicado)
2. 🔄 **Curto Prazo**: Testar build com Webpack
3. 📋 **Médio Prazo**: Dividir arquivo grande em componentes menores

## Como Aplicar a Solução Temporária

A solução já foi aplicada no `package.json`. Para testar:

```bash
cd sky-poc-frontend
npm run build
```

Se o build funcionar, você pode fazer deploy:

```bash
cd ../sky-poc-infra
export GH_PAT=seu_token
export VM_IP=172.191.77.30
export BRANCH=staging
./scripts/deploy-local-to-vm.sh
```

## Referências

- [Next.js Webpack vs Turbopack](https://nextjs.org/docs/app/api-reference/next-config-js/webpack)
- [Turbopack Limitations](https://turbo.build/pack/docs)
- [Code Splitting Best Practices](https://nextjs.org/docs/app/building-your-application/optimizing/lazy-loading)


