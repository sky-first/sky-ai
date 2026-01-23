# ⚠️ FIX 2: AÇÃO REQUERIDA - GRAFANA SECRETS

## Status Atual
- ❌ Você não tem acesso ao Azure Key Vault para criar secrets
- ✅ Arquivos YAML já estão configurados para usar ExternalSecrets
- ⏳ Aguardando: Admin ou pessoa com role "Key Vault Administrator"

## Comandos para o Admin Executar

Execute estes 3 comandos com acesso administrativo ao Key Vault:

```bash
# 1. Criar secret com password do Grafana
az keyvault secret set \
  --vault-name akv-sky-staging \
  --name grafana-admin-password \
  --value "jesusteama2026"

# 2. Criar secret com email do admin
az keyvault secret set \
  --vault-name akv-sky-staging \
  --name grafana-admin-email \
  --value "gustavo.mendonca@thedatafirst.com"

# 3. Criar secret com Slack webhook (pode deixar placeholder por enquanto)
az keyvault secret set \
  --vault-name akv-sky-staging \
  --name slack-webhook-url \
  --value "https://hooks.slack.com/services/TODO_ADD_SLACK_WEBHOOK_LATER"
```

## Validar que os Secrets Foram Criados

```bash
# Listar todos os secrets no Key Vault
az keyvault secret list --vault-name akv-sky-staging --query "[].name" -o table

# Resultado esperado:
# grafana-admin-email
# grafana-admin-password
# slack-webhook-url
```

## Próximas Etapas

Após o admin executar os 3 comandos:
1. ExternalSecret Operator sincronizará automaticamente (1-2 minutos)
2. Secrets Kubernetes serão criados no namespace `monitoring`
3. Grafana pod será reiniciado (automaticamente por Helm)
4. Você conseguirá fazer login no Grafana com:
   - Email: `gustavo.mendonca@thedatafirst.com`
   - Senha: `jesusteama2026`

## Referências
- Vault Name: `akv-sky-staging`
- Subscription: `e1070cf9-7790-4f2d-b449-d4bf4bc21906`
- Resource Group: `sky-aks-rg`
- Location: `eastus2`
