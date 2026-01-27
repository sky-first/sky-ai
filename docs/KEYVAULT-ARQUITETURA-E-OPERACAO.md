## Gestão de segredos com Azure Key Vault e AKS

Este documento descreve **como o Key Vault é usado nesta infra** e **como operar os segredos por ambiente**, alinhado às melhores práticas DevOps.

---

### 1. Visão geral

- **Um Key Vault por ambiente** é criado via Terraform em `infra/aks/security.tf`:
  - Recurso: `azurerm_key_vault.main`
  - Nome: `akv-sky-${var.environment}-${random_id.kv_suffix.hex}`
  - Resource Group: mesmo RG do AKS (por exemplo `sky-aks-staging-rg`)
- **Segredos de infraestrutura** (DB, Redis, URLs, JWT, encryption key) são **gerados automaticamente** por Terraform e gravados no Key Vault.
- O acesso dos pods no AKS ao Key Vault é feito via:
  - **User Assigned Identity** `azurerm_user_assigned_identity.eso` (`id-eso-${var.environment}`)
  - Federated credential com o OIDC do cluster (External Secrets Operator).

> Regra central: **nenhum segredo sensível deve ficar em YAML / `.tfvars` versionado**. O Key Vault é a fonte de verdade.

---

### 1.1. Matriz de responsabilidades (RACI simplificado)

| Papel              | Ação                                                                 | DevOps | SRE | Time de Segurança | Time de Aplicação |
|--------------------|----------------------------------------------------------------------|--------|-----|-------------------|-------------------|
| Criar Key Vault    | Novo cofre por ambiente via Terraform                               | R      | C   | A                 | I                 |
| Criar segredos de infra (DB/Redis/JWT/URLs) | Definidos/gerados pelo Terraform                         | R      | C   | A                 | I                 |
| Criar segredos de app (APIs externas, webhooks) | Via CLI/Portal ou script controlado                       | R      | C   | A                 | C                 |
| Ler valores de segredos em produção       | Apenas para debugging/incidente crítico                   | R      | R   | A                 | I                 |
| Rotacionar segredos de produção          | Seguir fluxo de rotação padronizado                       | R      | R   | A                 | C                 |
| Configurar acesso de SPs/Identidades     | RBAC em Key Vault / RG / Subscription                     | R      | C   | A                 | I                 |
| Consumir segredos nas apps               | Usar `Secrets` do Kubernetes / env vars                   | C      | C   | I                 | R                 |

Legenda: **R** = Responsável, **A** = Aprovador, **C** = Consultado, **I** = Informado.

---

### 2. Como o Terraform cria e usa o Key Vault

Arquivo principal: `infra/aks/security.tf`.

- **Criação do Key Vault**
  - Usa `data "azurerm_client_config" "current"` para identificar o tenant e o objeto (quem está rodando Terraform).
  - Habilita:
    - `soft_delete_retention_days = 7`
    - `enabled_for_disk_encryption = true`
  - Firewall:
    - `virtual_network_subnet_ids = [azurerm_subnet.aks.id]`
    - `ip_rules` derivados de `var.runner_ip` (para permitir acesso temporário de pipelines).

- **Access Policy para quem aplica Terraform**
  - `azurerm_key_vault_access_policy.current` concede ao identity que roda Terraform permissões completas de segredo:
    - `"Get", "List", "Set", "Delete", "Purge", "Recover"`

- **Identity para External Secrets (ESO)**
  - `azurerm_user_assigned_identity.eso` cria `id-eso-${var.environment}`.
  - `azurerm_key_vault_access_policy.eso` dá permissões mínimas para o ESO:
    - `"Get", "List"`
  - `azurerm_federated_identity_credential.eso` integra:
    - `issuer = azurerm_kubernetes_cluster.aks.oidc_issuer_url`
    - `subject = "system:serviceaccount:external-secrets:external-secrets"`

- **Segredos gerados automaticamente**
  - `random_password.postgres` → `postgres-password`
  - `random_password.redis` → `redis-password`
  - `azurerm_key_vault_secret.database_url` → `database-url`
  - `azurerm_key_vault_secret.redis_url` → `redis-url`
  - `random_password.jwt_secret` + `azurerm_key_vault_secret.jwt_secret_key` → `jwt-secret-key`
  - `random_password.encryption_key` + `azurerm_key_vault_secret.encryption_key` → `encryption-key`
  - `azurerm_key_vault_secret.openai_api_key` (placeholder) → `openai-api-key`
  - `azurerm_key_vault_secret.qdrant_url` → `qdrant-url`

> Sempre que o state é destruído, esses segredos podem ser **recriados**. Para ambientes críticos (prod), rotinas de backup/configuração externa são recomendadas.

---

### 2.1. Integração com CI/CD (GitHub Actions + OIDC)

Os workflows em `.github/workflows` autenticam no Azure usando **Service Principals**. A recomendação é:

- Usar `azure/login` com **OIDC** (federated credentials) para evitar `client_secret` fixo.
- Os SPs usados por Terraform e deploy:
  - Têm roles mínimas necessárias na subscription/RG.
  - Podem ter roles adicionais no Key Vault (por exemplo `Key Vault Secrets Officer` quando precisam criar segredos).
- O **runner** temporariamente recebe acesso ao Key Vault via:
  - `var.runner_ip` (para regras de firewall).
  - Role em nível de Key Vault/Resource Group conforme necessidade.

Assim, o pipeline segue o fluxo:

1. GitHub Actions → autentica no Azure via OIDC.
2. Terraform → cria/atualiza Key Vault, identidade ESO e segredos.
3. AKS/External Secrets → sincronizam segredos para os pods.

---

### 3. Obtendo o nome do Key Vault por ambiente

Após um `terraform apply` em `infra/aks`:

```bash
cd infra/aks
terraform output key_vault_name
```

Saída esperada (exemplo):

```text
akv-sky-staging-a1b2c3d4
```

Esse é o nome que deve ser usado para:

- Criar segredos manuais via CLI/Portal.
- Configurar External Secrets no cluster.
- Delegar permissões de RBAC (Key Vault roles) para Service Principals e Managed Identities.

---

### 4. Segredos gerados x segredos manuais

#### 4.1. Segredos gerados automaticamente por Terraform

Criados em `infra/aks/security.tf`:

- Senha do Postgres (`postgres-password`)
- Senha do Redis (`redis-password`)
- URLs de conexão (`database-url`, `redis-url`)
- Chave JWT (`jwt-secret-key`)
- Chave de criptografia (`encryption-key`)
- URL/Qdrant (`qdrant-url`)
- Placeholder para OpenAI (`openai-api-key`)

Esses segredos são **infraestrutura**. A aplicação e os manifests Kubernetes apenas consomem essas chaves, nunca as definem diretamente.

#### 4.2. Segredos manuais (exemplos)

Criados fora do Terraform, via CLI/Portal, seguindo docs como `FIX2-KEYVAULT-ACTIONS-REQUIRED.md`:

- Segredos de Grafana (`grafana-admin-password`, `grafana-admin-email`)
- Webhooks de Slack (`slack-webhook-url`)
- Chaves de APIs externas específicas de negócio (caso não queira versioná-las como placeholder no Terraform)

Recomendação:

- Produção: criar segredos manuais **apenas por usuários com role de Key Vault adequada** (`Key Vault Secrets Officer` / `Key Vault Administrator`).
- Não-prod: pode usar scripts utilitários (por exemplo `scripts/populate-kv-prod-secrets.sh` adaptado para o ambiente) para carregar um `.env` local.

---

### 5. Fluxo de acesso: Key Vault → External Secrets → Pods

1. Terraform cria:
   - Key Vault do ambiente.
   - Segredos de infraestrutura.
   - User Assigned Identity `id-eso-${var.environment}`.
   - Federated credential ligando o ESO ao OIDC do AKS.
2. No cluster, o **External Secrets Operator**:
   - Usa a identidade `id-eso-${var.environment}`.
   - Lê segredos do Key Vault (`Get`/`List`).
   - Cria/atualiza `Secret` Kubernetes nos namespaces das aplicações.
3. Os Deployments/Pods:
   - Montam os `Secrets` via env vars ou `envFrom`.
   - Nunca acessam o Key Vault diretamente.

Validações recomendadas:

```bash
# Verificar External Secrets
kubectl get externalsecrets -A

# Ver Secret gerado em um namespace
kubectl get secret <nome-do-secret> -n <namespace> -o yaml
```

---

### 6. Boas práticas operacionais

- **Nunca** commitar valores de segredos em:
  - `.tfvars`
  - manifests YAML
  - scripts `.sh` / `.ps1`
- Usar `.env.example` como **catálogo de variáveis**, não como fonte real de segredos.
- Para rotação:
  - Atualizar o segredo no Key Vault (ou criar uma nova versão).
  - Aguardar sincronização do External Secrets e confirmar o `Secret` no namespace.
  - Monitorar pods/health-checks (scripts em `scripts/validate-*.sh` e dashboards em `monitoring/`).
- Para debug:
  - Preferir validações via Kubernetes e logs.
  - Acesso direto ao valor bruto do segredo no Key Vault deve ser restrito a poucas pessoas (DevOps/SRE).

#### 6.1. Anti‑padrões (NÃO fazer)

- Salvar segredos em:
  - Issues, tickets, planilhas, chats, screenshots.
  - Variáveis de ambiente definidas diretamente na linha de comando de produção.
- Criar segredos **com nomes diferentes por ambiente** sem padrão (dificulta External Secrets e scripts).
- Rotacionar segredos de produção:
  - fora de janela controlada,
  - sem validação em staging antes,
  - sem monitorar métricas/alertas após a troca.

Sempre que um desses casos for necessário em incidente crítico, deve ser registrado em runbook ou post-mortem.

#### 6.2. Fluxo padrão de rotação de segredos

1. **Planejar**
   - Identificar o segredo (ex.: `postgres-password`) e sistemas impactados.
   - Validar se existe ambiente de staging equivalente.
2. **Rotacionar em staging**
   - Atualizar o segredo no Key Vault de staging.
   - Verificar:
     - `kubectl get externalsecret -n <ns>`
     - `kubectl get secret <nome> -n <ns> -o yaml`
   - Rodar scripts de validação (`scripts/validate-*.sh`) e smoke tests.
3. **Rotacionar em produção**
   - Repetir o processo no Key Vault de prod.
   - Verificar sincronização no cluster.
   - Acompanhar dashboards e alertas por um período definido (ex.: 30–60 minutos).
4. **Limpeza e registro**
   - Garantir que versões antigas não são mais usadas.
   - Registrar a rotação (data, responsável, motivo) no runbook ou sistema de mudanças.

---

### 7. Próximos passos recomendados

1. Garantir que todos os ambientes (dev/staging/prod) estão usando o padrão:
   - Key Vault criado por Terraform.
   - ESO com identidade dedicada.
   - Segredos de infra gerados automaticamente.
2. Migrar qualquer segredo ainda presente em YAML/variáveis de ambiente manuais para o Key Vault.
3. Integrar scripts de validação de segredos e External Secrets em pipelines de CI/CD (GitHub Actions).

---

### 8. Exemplos práticos por ambiente

#### 8.1. Staging

- Descobrir nome do Key Vault:

  ```bash
  cd infra/aks
  terraform workspace select staging # se estiver usando workspaces
  terraform output key_vault_name
  ```

- Validar External Secrets no cluster de staging:

  ```bash
  kubectl config use-context <aks-staging-context>
  kubectl get externalsecrets -A
  kubectl get secret <nome-do-secret> -n <namespace> -o yaml
  ```

Uso típico:

- Testar primeiro qualquer novo segredo ou rotação em staging.
- Ajustar manifests e External Secrets até tudo ficar estável.

#### 8.2. Produção

- Mesmo fluxo, porém com controles adicionais:
  - Alterações em segredos devem seguir processo de change management.
  - Acesso ao Portal/CLI para ler valores deve ser feito apenas por DevOps/SRE de plantão.
- Validações obrigatórias:
  - Rodar scripts de health-check e validação (`scripts/validate-monitoring-prod.sh`, `scripts/validate-env.sh`, etc.).
  - Revisar dashboards críticos (latência, erros 5xx, health dos pods) após mudanças de segredos.

Este documento deve ser lido em conjunto com:

- `PRODUCTION-RUNBOOK.md`
- `PROD-REMEDIATION-CHECKLIST.md`
- `FIX2-KEYVAULT-ACTIONS-REQUIRED.md`

para formar a visão completa de operação segura em produção.

