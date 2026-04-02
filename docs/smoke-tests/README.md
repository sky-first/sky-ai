# [DEVOPS] Operação de Smoke Tests

Os **Smoke Tests** são executados automaticamente após cada deploy via ArgoCD (`PostSync`). Eles garantem que a jornada crítica do usuário (Frontend -> Ingress -> WAF -> Backend -> Banco) está íntegra.

## 🕵️ Como Diagnosticar Falhas

Se o ArgoCD marcar os Smoke Tests como `Failed`:

1. **Verifique os Logs do Job**:

   ```bash
   kubectl logs -n staging -l job-name=sky-smoke-test-job
   ```

2. **Identifique a Causa Raiz**:
   * **HTTP 502/504**: Provavelmente o Backend está reiniciando ou o Upstream no Nginx falhou.
   * **HTTP 403**: O **WAF (ModSecurity)** pode estar bloqueando a requisição. Verifique o ConfigMap `ingress-nginx-modsecurity-exclusions`.
   * **HTTP 000/Connection Refused**: Problema de rede ou DNS no Ingress.

## 🔄 Procedimento de Rollback

Se o Smoke Test falhar e a aplicação estiver inacessível:

1. **Rollback ArgoCD**: Use o botão "Rollback" no ArgoCD para a versão anterior estável.
2. **Verificação Manual**: Após o rollback, execute o script localmente para garantir que o ambiente voltou ao normal:

   ```bash
   ./scripts/smoke-test.sh
   ```

## 🛠️ Manutenção do Script

O script reside em `scripts/smoke-test.sh` e é injetado no cluster via o ConfigMap `sky-smoke-test-script`. Para alterar a lógica de teste:

1. Altere o arquivo local.
2. Aplique a mudança no GitOps.
3. O ArgoCD atualizará o ConfigMap e os próximos testes usarão a nova lógica.
