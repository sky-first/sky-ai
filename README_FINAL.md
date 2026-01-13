# 🚀 Sky POC Infrastructure (V4.1) - Operational Guide

Este documento confirma a entrega dos itens do backlog e guia a execução.

## ✅ Rastreabilidade (O que foi entregue)

| Item do Backlog | Status no Código | Onde encontrar |
| :--- | :--- | :--- |
| **DO2025-534 Levantamento e planejamento** | ✅ Concluído | `implementation_plan.md`, `architecture_v4.md` |
| **DO2025-535 Configuração de acesso ao AKS** | ✅ Concluído | `infra/aks/bastion.tf` (SSH), `oidc.tf` (GitHub Actions) |
| **DO2025-536 Criação dos namespaces** | ✅ Automatizado | `gitops/apps/*.yaml` (ArgoCD cria auto com `CreateNamespace=true`) |
| **DO2025-537 Preparação dos secrets** | ✅ Concluído | `infra/aks/database.tf` (Gera senhas), `gitops/charts/.../secret.yaml` |
| **DO2025-538 Integração com Azure** | ✅ Concluído | `infra/aks/oidc.tf` (Auth sem segredo), `network.tf` (VNet Integration) |
| **DO2025-539 Validação com deploy de teste** | ⚠️ Pronto p/ Executar | `scripts/smoke-tests.sh` + `deploy-template.yml` |

---

## 🛠️ Como Executar (Passo a Passo)

### 1. Provisionar Infraestrutura (Terraform)
Isso cria a VNet, AKS, Banco de Dados e Redis.

```bash
cd infra/aks
# Login na Azure
az login

# Inicializar e Aplicar
terraform init
terraform apply -out=main.tfplan
# Digite 'yes'

# Configure os Segredos (Key Vault -> Cluster)
# Configure os Segredos (Key Vault -> Cluster)
../../scripts/configure-eso.sh
```

### 2. Instalar Plataforma (GitOps)
Isso instala o ArgoCD, Ingress e Observabilidade.

```bash
# Conectar no Cluster (via Bastion ou direto se tiver acesso)
az aks get-credentials -g sky-aks-rg -n sky-aks-cluster

# Rodar script de instalação
cd ../../gitops/argocd
./install.sh
```

### 3. Deploy da Aplicação (App of Apps)
O ArgoCD vai detectar os arquivos em `gitops/bootstrap/` e subir:
- `backend` (API + Migração de Banco)
- `frontend` (UI + Autoscaling)

### 4. Acessar
- **URL**: `https://sky.example.com` (Definido no Ingress)
- **Grafana**: `https://grafana.sky.example.com`

---

## 🏢 Multi-Tenancy (Grandes Clientes)
Para subir um ambiente dedicado ("Mansão"):

```bash
cd infra/aks
../scripts/manage-tenant.sh apply client-vip
```
