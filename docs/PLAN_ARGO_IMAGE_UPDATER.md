# Plano de Implementação: ArgoCD Image Updater (Git Write-Back)

## 1. O que é?
O **ArgoCD Image Updater** é um componente oficial que roda dentro do seu cluster Kubernetes. Ele:
1.  Monitora o seu Container Registry (ACR) procurando novas tags de imagem.
2.  Quando encontra uma nova tag (que segue o padrão definido), ele **clona seu repositório Git**, edita o arquivo `.yaml` e faz o **commit + push**.
3.  O ArgoCD nativo detecta o commit e sincroniza a aplicação.

## 2. Por que usar com "Git Write-Back"?
Essa é a melhor prática para GitOps porque mantém seu repositório Git como a **Fonte da Verdade**. Você sempre saberá exatamente qual versão da imagem rodou em qual momento apenas olhando o histórico do Git.

---

## 3. Estratégia de "Validação Obrigatória" (Pull Request Flow)

Para respeitar sua regra de *"nunca enviar sem validar"* e contornar a proteção das branches `main` e `staging`, configuraremos o Image Updater para **não fazer push direto na main**.

### Fluxo Proposto:
1.  **Staging (Automático)**:
    *   Monitora imagens com filtro `staging-.*`.
    *   Faz o commit direto na branch `staging` (Se permitir direct push ou via token de bypass, OU usamos branch separada `auto/staging`).
    
2.  **Produção (Validado)**:
    *   Monitora imagens com filtro `prod-.*` (ou releases numéricas).
    *   O Updater fará o commit em uma **nova branch** (ex: `image-update/sky-poc-ai-v1.2`).
    *   Ele **NÃO** atualiza a `main` sozinho.
    *   **A Validação**: Você verá a branch nova no GitHub, abrirá um Pull Request (PR), revisará e aprovará o merge.
    *   Após o merge, o ArgoCD aplica em Produção.

---

## 4. Pré-requisitos para Instalação

Precisamos aplicar um manifesto que instala o `argocd-image-updater` no namespace `argocd`.

### Credenciais Necessárias:
1.  **Git Access**: Um Token (PAT) do GitHub com permissão `repo` para ler/escrever no repo de infra.
2.  **ACR Access**: Credenciais para ler o Azure Container Registry (já temos no cluster, mas o updater precisa de config específica).

## 5. Exemplo de Configuração (Application)

Você terá que editar o arquivo `ai.yaml` adicionando anotações como esta:

```yaml
metadata:
  annotations:
    # Habilitar o updater para esta aplicação
    argocd-image-updater.argoproj.io/image-list: my-image=skyacrprodel5zpw.azurecr.io/sky-poc-ai:^sha-.*
    
    # Método de escrita: Git
    argocd-image-updater.argoproj.io/write-back-method: git
    
    # Branch alvo para o commit (para Produção, usamos uma branch de PR)
    argocd-image-updater.argoproj.io/write-back-target: "update-prod-branch"
```

## Próximo Passo
Se você aprovar este plano, eu irei:
1.  Criar o manifesto de instalação do `argocd-image-updater`.
2.  Configurar o Secret com o Token do GitHub (precisarei que você confirme se posso usar o existente ou se geramos um novo).
3.  Aplicar no cluster.
