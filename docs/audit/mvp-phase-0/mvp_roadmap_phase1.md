# 🚀 Roadmap Pós-MVP: Escalonando para 5 Clientes Enterprise (Phase 1)

**Autor:** Principal Distinguished Engineer
**Objetivo:** Transformar o "MVP Blindado" em "Plataforma Enterprise Gerenciável".

## 📊 Onde Estamos (O Status Atual)
*   **Estabilidade:** ✅ **Resolvida** (Limits no Postgres impedem crash).
*   **Segurança de Dados:** ✅ **Resolvida** (Backup diário para Azure Blob).
*   **Gaps Atuais (Onde estamos "errando" conscientemente):**
    1.  **Cegueira Operacional:** Se o backup falhar amanhã, ninguém sabe. (Falta Alerta).
    2.  **Lixo Digital:** Os backups de 2026 ficarão lá para sempre. (Falta Limpeza/Lifecycle).
    3.  **Segurança Estática:** A aplicação ainda lê senhas de Secrets do K8s. (Falta Workload Identity na App).

---

## 🗺️ O Plano de Batalha (Phase 1 - Mês 2)

### 1. 👁️ Observabilidade Ativa (Alerting)
**O Problema:** CronJobs falham silenciosamente.
**A Solução:** Prometheus Rule para detectar falha no Job.
*   **Subtask 1.1:** Criar `PrometheusRule` que dispara se `kube_job_status_failed > 0`.
*   **Subtask 1.2:** Configurar AlertManager para enviar slack/email para o time de DevOps.
*   **Resultado:** "Dormir tranquilo". Se o backup falhar, o telefone toca.

### 2. 🧹 Higiene de Dados (Lifecycle Management)
**O Problema:** Custo infinito de storage e compliance (GPDR/LGPD requer exclusão).
**A Solução:** Azure Storage Lifecycle Policy.
*   **Subtask 2.1:** Adicionar no Terraform `azurerm_storage_management_policy`.
*   **Regra:** "Deletar blobs no container `postgres-backups-staging` com mais de 30 dias".
*   **Resultado:** Custo fixo e previsível da Azure.

### 3. 🔐 Zero Trust Identity (Workload Identity Completo)
**O Problema:** Rotacionar senhas é dor de cabeça. Secrets no cluster são risco.
**A Solução:** A aplicação (`sky-be`) se autentica no Postgres/KeyVault usando seu ServiceAccount.
*   **Subtask 3.1:** Alterar código da App (Python) para usar `DefaultAzureCredential`.
*   **Subtask 3.2:** Federar ServiceAccount `sky-be` com Managed Identity.
*   **Resultado:** Zero credenciais estáticas. A aplicação "é" a identidade.

### 4. 🧪 Disaster Recovery Automatizado (The "Chaos Monkey")
**O Problema:** "Backup de Schrödinger" (você só sabe se funciona quando precisa).
**A Solução:** Um Job semanal que restaura o backup em um banco temporário.
*   **Subtask 4.1:** CronJob semanal `restore-test` que sobe um Postgres vazio, baixa o último backup e restaura.
*   **Resultado:** Prova matemática de que os dados são recuperáveis.

---

## 📈 Resumo da Evolução

| Dimensão | Phase 0 (HOJE - MVP) | Phase 1 (Mês 2 - 5 Clientes) |
| :--- | :--- | :--- |
| **Backup** | Diário (Automático) | Monitorado + Teste de Restore |
| **Retenção** | Infinita (Manual) | Automática (30 dias) |
| **Identidade** | Secrets K8s | Azure AD Workload Identity |
| **Nível de Sono** | "Verificar logs todo dia" | "Dormir até o Alerta tocar" |

## ✅ Próximos Passos Imediatos (Para Fechar Hoje)
1.  **Merge PR:** Aprovar `feat/mvp-hardening-backup`.
2.  **Monitoramento Manual:** Colocar na agenda "Verificar Backup" toda segunda-feira até a Phase 1.
3.  **Celebrar:** O MVP está pronto para a guerra.
