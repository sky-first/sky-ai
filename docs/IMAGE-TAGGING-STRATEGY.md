# Image Tagging Strategy - Production Fix

## Problema Atual
```yaml
tag: "latest"  # Mutable, security risk
```

## Solução Implementada
Atualizar CI/CD pipeline (GitHub Actions) para usar git commit SHA como tag.

## Configuração Necessária em GitHub Actions

```yaml
# .github/workflows/build-and-push.yml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build and Push Image
        env:
          REGISTRY: skyacrstaging.azurecr.io
          IMAGE_NAME: sky-poc-backend  # ou frontend/ai
        run: |
          # Obter git commit SHA (short form)
          COMMIT_SHA=$(git rev-parse --short HEAD)
          
          # Build image
          docker build -t $REGISTRY/$IMAGE_NAME:$COMMIT_SHA .
          docker build -t $REGISTRY/$IMAGE_NAME:latest .  # Keep latest para fallback
          
          # Push ambas as tags
          docker push $REGISTRY/$IMAGE_NAME:$COMMIT_SHA
          docker push $REGISTRY/$IMAGE_NAME:latest
          
          # Output para ArgoCD usar
          echo "IMAGE_TAG=$COMMIT_SHA" >> $GITHUB_OUTPUT
```

## Atualizar ArgoCD Applications

```yaml
# Mudar de:
tag: "latest"

# Para:
tag: "{{ .Values.imageTag }}"  # Renderizado pelo CI/CD
```

## Status
- ⚠️ PRECISA ATUALIZAR: GitHub Actions workflow
- ⚠️ PRECISA ATUALIZAR: Helm values no chart common-app
- ✅ DOCUMENTADO: Strategy para produção

## Impacto
- ✅ Supply chain security melhorado
- ✅ Rollback simples (revert para SHA anterior)
- ✅ Auditoria clara de qual versão está em prod
