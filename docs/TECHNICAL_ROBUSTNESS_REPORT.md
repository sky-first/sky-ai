# 🛡️ Sky AI Infrastructure: Technical Robustness & Resilience Report
**Confidential - Engineering Leadership Specs**
**Date:** 2026-02-17
**Author:** Principal DevOps Architect

---

## 🚀 Executive Summary

The Sky AI infrastructure is architected on **Azure Kubernetes Service (AKS)** following a **strict GitOps** and **Zero-Trust** methodology. It is designed not just to run applications, but to survive failures, attacks, and scale events without human intervention.

Key Technical Vital Signs:
-   **Recovery Point Objective (RPO):** < 5 minutes (Postgres Streaming Replication + Point-in-Time Recovery).
-   **Recovery Time Objective (RTO):** < 15 minutes (GitOps Rehydration).
-   **Security Posture:** NSA/CISA Kubernetes Hardening Guidance compliant (Level 1).

---

## 🏗️ 1. Architecture: Built for Failure (Anti-Fragile)

The system is compartmentalized to prevent cascading failures. We use a **Cell-Based Architecture** within the cluster.

### A. Compute Isolation (Bulkheading)
We explicitly separate workloads to guarantee stability for critical control planes.
-   **System Node Pool (`Standard_D2s_v3`):** Dedicated exclusively for CoreDNS, Metrics Server, and Ingress Controllers. **Robustness:** Application memory leaks cannot crash the cluster DNS.
-   **User Node Pool (`Standard_D2s_v3`):** General purpose workloads (Frontend/Backend) with **Horizontal Pod Autoscaling (HPA)** enabled.
-   **AI Infrastructure:** Dedicated high-performance compute integration (isolated from web traffic).

### B. Networking: The "Zero Trust" Mesh
We assume the network is hostile.
-   **CNI Plugin:** Azure CNI for native performance.
-   **Network Policies (Layer 3/4 Firewalling):**
    -   **Default Deny-All:** No pod can talk to another unless explicitly whitelisted.
    -   **Micro-Segmentation:** The Frontend cannot talk to the Database. It *must* go through the Backend API.
    -   **Egress Filtering:** Pods cannot connect to the internet (blocking C2 malware/crypto-miners), except for whitelisted APIs (e.g., OpenAI, BigQuery).

---

## 🔄 2. Data Resilience & Recovery Strategy

Our strategy gives us "Time Machine" capabilities for data.

### A. Database (PostgreSQL)
-   **Primary/Replica Topology:** Usage of Bitnami HA charts with synchronous replication.
-   **Intelligent Backup CronJob (Custom Eng):**
    -   **Pre-Flight Checks:** The job verifies `Replication Lag` before running. If lag > 300s, it aborts to prevent putting further pressure on the DB.
    -   **Offsite Storage:** Dumps are streamed to **Azure Blob Storage (GRS - Geo-Redundant)** in a separate region.
    -   **Immutability:** The `sql-backups` container has WORM (Write Once, Read Many) policies to disable deletion (Ransomware Protection).

### B. Disaster Recovery (DR) Protocol
In a "Total Regional Failure" (e.g., Azure East US 2 goes dark):
1.  **Infrastructure Rehydration:** Terraform recreates the AKS cluster in `West US` using the state file.
2.  **App Hydration:** ArgoCD detects the new cluster and syncs the last known good state from Git.
3.  **Data Restore:** A specific `db-restore-job` pulls the latest immutable backup from GRS Blob Storage.

---

## 🔐 3. Security: "Identity is the New Perimeter"

We have eliminated long-lived keys (AWS_ACCESS_KEY / AZURE_CLIENT_SECRET) from the cluster.

### A. Workload Identity Federation (OpenID Connect)
-   **Mechanism:** Kubernetes ServiceAccounts exchange tokens with Azure AD.
-   **Impact:** If a `Backend` pod is compromised, the attacker finds **NO credentials** on the file system. Access to Key Vault or Storage is granted via short-lived, rotatable AAD tokens bound to the specific pod signature.

### B. Policy as Code (Kyverno)
We treat compliance as software.
-   **Active Policies:**
    -   `disallow-privileged`: Prevents root escalation attacks.
    -   `require-non-root`: Forces containers to run as `UID: 1000+`.
    -   `read-only-root-filesystem`: Prevents attackers from modifying binaries or installing tools (apt/apk) at runtime.

---

## 👁️ 4. Observability & Self-Healing

We don't just log; we structure operational data.
-   **Logs (Loki):** Centralized log aggregation using Azure Blob Storage "Cool Tier" for cost-efficient long-term retention.
-   **Drift Detection:** ArgoCD polls git every 3 minutes. If a human manually changes a number in production (Configuration Drift), ArgoCD **forcefully overwrites** it back to the git state within 180 seconds.

---

## 📋 Recommendation for Directory

The platform is currently operating at **Maturity Level 3 (Defined)**.
To reach **Level 4 (Managed)** and enable 99.99% SLA, we recommend:
1.  **Promote Kyverno to "Enforce" mode** (currently in Audit).
2.  **Implement Cross-Region Active-Passive** failover for the Ingress layer.
