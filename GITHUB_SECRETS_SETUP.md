# GitHub Secrets Setup Guide

## Required Secrets for Each Repository

You need to add the following secrets to **each** of your three repositories:
- `sky-first/sky-poc-backend`
- `sky-first/sky-poc-frontend`
- `sky-first/sky-poc-ai`

### How to Add Secrets

1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add each of the following secrets:

### Secrets to Add

| Secret Name | Value |
|-------------|-------|
| `AZURE_CLIENT_ID` | `f9071b26-a155-4e9b-b8f2-c6a50ebe3ef3` |
| `AZURE_TENANT_ID` | `a1b3ce06-b7ba-4d99-8a26-3347ab865f36` |
| `AZURE_SUBSCRIPTION_ID` | `e1070cf9-7790-4f2d-b449-d4bf4bc21906` |

## Workflow Files to Copy

### Backend Repository (`sky-poc-backend`)

Copy the file:
```
.github-workflows/backend-build-deploy.yml
```

To your repository at:
```
.github/workflows/build-deploy.yml
```

### Frontend Repository (`sky-poc-frontend`)

Copy the file:
```
.github-workflows/frontend-build-deploy.yml
```

To your repository at:
```
.github/workflows/build-deploy.yml
```

### AI Repository (`sky-poc-ai`)

Copy the file:
```
.github-workflows/ai-build-deploy.yml
```

To your repository at:
```
.github/workflows/build-deploy.yml
```

## Testing the Pipeline

After adding secrets and workflow files:

1. **Commit and push** the workflow file to the `staging` branch
2. The workflow will **automatically trigger**
3. Monitor the build in **Actions** tab of your repository
4. After ~3-5 minutes, check ACR for the new image:
   ```bash
   az acr repository list --name skyacrstaging -o table
   ```

## ArgoCD Auto-Sync Configuration

ArgoCD is configured to check for new images every 3 minutes. Once your image is in ACR, ArgoCD will automatically:
1. Detect the new image
2. Update the deployment
3. Roll out the new pods

You can monitor this with:
```bash
kubectl get applications -n argocd
kubectl get pods -n staging -w
```

## Troubleshooting

### If workflow fails with "authentication failed"
- Verify secrets are added correctly (no extra spaces)
- Check that federated credentials are configured for the correct repository

### If image push fails
- Verify Service Principal has `AcrPush` role
- Check ACR name is correct (`skyacrstaging`)

### If ArgoCD doesn't detect new image
- Verify image tag matches what's in the Application manifest (`latest` for staging)
- Force sync: `kubectl patch application <app-name> -n argocd -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'`
