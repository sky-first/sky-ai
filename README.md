# Sky AI POC Infrastructure - Architecture Overview

## 🏗️ High-Level Architecture

This project implements a **GitOps-driven**, **Cloud-Native** architecture on **Azure Kubernetes Service (AKS)**. It is designed for resilience, scalability, and security, following DevSecOps best practices.

### 🌐 System Architecture Diagram

```mermaid
graph TD
    subgraph "Azure Cloud"
        subgraph "Network (VNet)"
            Bastion[🔐 Bastion Host]
            
            subgraph "AKS Cluster"
                Ingress[🚦 Nginx Ingress Controller]
                
                subgraph "Workloads (Namespaces)"
                    Frontend[💻 Frontend App]
                    Backend[⚙️ Backend API]
                    Worker[🤖 AI Worker]
                end
                
                subgraph "AI Infrastructure"
                    Ollama[🧠 Ollama Service]
                    AIPool[🚀 Node Pool: AI Turbo (F16s_v2)]
                end
                
                subgraph "Data Layer"
                    Postgres[(🐘 PostgreSQL)]
                    Redis[(⚡ Redis Cache)]
                end
                
                subgraph "Platform Services"
                    ArgoCD[🐙 ArgoCD (GitOps)]
                    ESO[🔑 External Secrets]
                    CertManager[🔒 Cert Manager]
                    Observability[📊 Prometheus/Grafana/Loki]
                end
            end
        end
        
        KV[🔑 Azure Key Vault]
        ACR[📦 Azure Container Registry]
        Storage[💾 Azure Blob Storage (TF State)]
    end

    User[👤 User] -->|HTTPS| Ingress
    Ingress --> Frontend
    Ingress --> Backend
    
    Frontend --> Backend
    Backend --> Postgres
    Backend --> Redis
    Backend --> Worker
    Worker --> Ollama
    
    Ollama -.->|Scheduled on| AIPool
    
    ESO <-->|Syncs Secrets| KV
    ArgoCD <-->|Syncs Manifests| GitHub[🐙 GitHub Repo]
    
    GitHub -->|CI/CD Action| ACR
    Terraform[🛠️ Terraform] <-->|Manages| Azure Cloud
```

---

## 🧩 Component Breakdown

### 1. Infrastructure (Terraform)
- **State Management**: Remote state in Azure Blob Storage with lease locking.
- **Compute**:
  - **AKS Cluster**: Managed Kubernetes with OIDC and Workload Identity enabled.
  - **Node Pools**:
    - `system`: Core system services (2x `Standard_D2s_v3`).
    - `userapps`: General application workloads (1-3x `Standard_D2s_v3`, Auto-scaling).
    - `aicpu16`: Dedicated high-performance pool for AI/LLM inference (0-1x `Standard_F16s_v2`, scales to 0 when unused).
- **Networking**:
  - **VNet**: `sky-aks-vnet` with segmented subnets (`aks-subnet`, `bastion-subnet`).
  - **Security**: Private access options, Bastion host for secure SSH tunneling.

### 2. Platform & Operations (GitOps)
- **ArgoCD**: The source of truth for all Kubernetes manifests. Automatically syncs changes from `gitops/bootstrap`.
- **Secret Management**: **External Secrets Operator** integrates with **Azure Key Vault**. No secrets are stored in Git.
- **Security**:
  - **Kyverno**: Enforces policies (e.g., non-root containers, required labels).
  - **Network Policies**: Restricts traffic between namespaces and pods (Zero Trust/Least Privilege).
- **Observability**: Full stack monitoring with Prometheus (Metrics), Grafana (Visualization), and Loki (Logs).

### 3. Application Stack
- **Frontend**: React-based web interface.
- **Backend**: API service handling business logic.
- **AI Services**:
  - **Ollama**: Local LLM inference engine running on dedicated compute-optimized nodes.
  - **AI Worker**: Async worker for processing AI tasks.
- **Databases**:
  - **Postgres**: Relational data storage.
  - **Redis**: Caching and message broker.

### 4. CI/CD Pipeline (GitHub Actions)
- **Infrastructure**: Automated Terraform Plan/Apply on PRs and merges to `staging`/`main`.
- **Application**: Builds Docker images, pushes to ACR, and updates Kubernetes manifests via GitOps.

## 🚀 Key Design Decisions

1.  **Separation of Concerns**: Infrastructure (Terraform) is decoupled from Application Deployment (ArgoCD).
2.  **Cost Optimization**: The `aicpu16` node pool scales to zero when no AI tasks are running, saving significant compute costs.
3.  **Security First**:
    -   **Workload Identity**: Pods authenticate to Azure resources (Key Vault, ACR) without long-lived credentials.
    -   **Read-Only Root**: Containers are configured to run as non-root users where possible.
4.  **Resilience**:
    -   **HPA**: Horizontal Pod Autoscalers configured for application services.
    -   **PDB**: Pod Disruption Budgets ensure availability during upgrades.

## 📂 Repository Structure

- `infra/aks`: Terraform configurations for Azure infrastructure.
- `gitops/`: Kubernetes manifests and Helm charts.
    - `bootstrap/`: Root applications for ArgoCD.
    - `mainfests/`: Raw Kubernetes YAMLs for workloads.
    - `charts/`: Custom Helm charts.
- `.github/workflows`: CI/CD automation pipelines.
- `docs/`: Detailed operating procedures and documentation.
