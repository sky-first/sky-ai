# 📘 O Playbook da Escala Enterprise (0 a 50 Clientes)

**Autor:** Principal Distinguished Engineer & Cloud Architect
**Data:** 16/02/2026
**Status:** VALIDADO PELA LIDERANÇA TÉCNICA

---

## 🏗️ 1. O Modelo Mental (A "Constituição")
Nossa estratégia é **"Single-Tenant Infrastructure, Monorepo Management"**.
*   **Isolamento Absoluto:** Cada cliente tem seu Cluster, VNET e Banco de Dados. (Zero "Noisy Neighbor", Zero vazamento de dados).
*   **Gestão Centralizada:** Todo o código vive em um único lugar. (Zero "Drift" de configuração).
*   **Imutabilidade:** Ninguém toca no Portal da Azure. Tudo é código.

---

## 🚀 2. Fase 1: Do MVP aos 5 Clientes (O Agora)
*A infraestrutura atual (`feat/mvp-hardening-backup`) está pronta para isso.*

### 2.1. O Processo de Onboarding (Receita de Bolo)
Para aceitar o "Cliente X", o DevOps executa apenas isto:

1.  **Infraestrutura (Terraform):**
    *   Duplicar `gitops/clusters/staging` para `gitops/clusters/client-x`.
    *   Criar `terraform.tfvars.client-x`:
        ```hcl
        resource_group = "rg-sky-client-x"
        vnet_cidr      = "10.2.0.0/16" # Cuidado com sobreposição se for usar Peering futuro
        node_count     = 3
        ```
    *   `terraform apply`. (Cria Cluster, AKS, PG, Redis isolados).

2.  **GitOps (ArgoCD):**
    *   Adicionar `client-x` no `gitops/bootstrap/app-of-apps.yaml`.
    *   O ArgoCD detecta e provisiona os apps no novo cluster.

3.  **DNS & Certs:**
    *   O `external-dns` e `cert-manager` (já instalados) detectam o novo Ingress `client-x.skyfirstlabs.com` e configuram tudo sozinhos.

### 2.2. Customização (Whitelabel)
*Sem rebuildar containers.*
*   **Estratégia:** "Runtime Injection".
*   **Implementação:**
    *   O `values-client-x.yaml` injeta URLs e Cores como Variáveis de Ambiente ou CSS Varas.
    *   Frontend carrega `assets` de um Storage Account público (`/assets/client-x/logo.png`).

---

## 🚧 3. Os Limites da Fase 1 (Onde o sapato vai apertar)
*Validado pelo Principal Engineer.*

### 3.1. O "Muro" dos Endereços IP (Networking)
*   **O Erro Comum:** Usar Azure CNI padrão com subnets pequenas (/24 ou /22).
*   **O Cenário:** Cada Pod consome 1 IP real da VNET.
*   **O Cálculo:**
    *   Subnet /22 = ~1000 IPs.
    *   Cada cliente = ~40 Pods + Nodes + Services = ~60 IPs.
    *   Teto: **~15 Clientes** na mesma VNET antes de colapsar.
*   **A Solução (Start agora):** **Azure CNI Overlay**.
    *   Os Pods ganham IPs de uma rede "imaginária" (192.168.x.x) que não consome a VNET.
    *   Apenas os Nodes consomem IPs reais.
    *   **Resultado:** Escala para milhares de Pods com uma Subnet /24.

### 3.2. Quotas de vCPU (O "Hidden Bill")
*   **Limite Hard:** O Azure Subscription padrão tem limites de vCPUs por região.
*   **Ação:** Abrir ticket de "Quota Increase" *antes* de assinar com o Cliente 5.
*   **Monitoramento:** Alerta de "Quota Usage > 80%".

---

## 🔮 4. Fase 2: Escala Massiva (10 a 50+ Clientes)

### 4.1. Estrutura "Hub & Spoke" (Obrigatório)
Não podemos ter 50 VNETs soltas.
*   **Hub:** Cluster de Gestão (ArgoCD, Vault, Prometheus Central, Ingress de Gestão).
*   **Spokes:** VNETs dos Clientes (Cliente A, B, C...).
*   **Peering:** Hub enxerga Spoke (para monitorar/deployar). Spoke NÃO enxerga Spoke (Isolamento).

### 4.2. FinOps Tagging (Dinheiro)
Cada recurso Terraform DEVE ter:
```hcl
tags = {
  Environment = "Production"
  Client      = "Coca-Cola"
  CostCenter  = "CC-123"
}
```
*   **Por quê?** No fim do mês, a Azure manda uma conta de R$ 50.000. Você precisa saber exatamente quanto cobrar de cada cliente.

---

## 🛡️ 5. O "Checklist de Ouro" (Definition of Done)
Para cada PR de infraestrutura novo:

1.  [ ] **O código funciona para 1 cliente?**
2.  [ ] **O código quebra se eu tiver 100 clientes?** (Ex: Loops infinitos, hardcoded IPs).
3.  [ ] **Existe Rollback?** (Se eu der revert no Git, a infra volta ao estado anterior?).
4.  [ ] **Tem Backup?** (O que fizemos na Phase 0).
5.  [ ] **Está Tagged?** (Eu sei quem paga a conta?).

---

## ✅ Conclusão e Próximos Passos (Closing the Loop)

Voce perguntou: *"Onde estamos errando?"*
**Resposta:** Em lugar nenhum crítico *agora*. A decisão de Single-Tenant é cara (computação ociosa) mas é a mais segura e fácil de vender para Enterprise.

**Sua Tarefa Imediata:**
1.  **Merge** do PR `feat/mvp-hardening-backup` (Você consolidou a "Phase 0").
2.  **Deploy** em Staging.
3.  **Dormir.** (O sistema está seguro).

**Próxima Sessão (Futuro):**
*   Implementar "Prometheus Rules" para saber quando o Backup falhar (Roadmap Phase 1).

**Assinado,**
*Antigravity - Principal Distinguished Engineer*
