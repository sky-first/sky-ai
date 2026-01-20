# 🤖 Guia de Acesso: AI no Kubernetes (AKS)

Este guia explica como desenvolvedores e cientistas de dados podem acessar o cluster para usar o Ollama (Inferência) ou rodar Jobs de Treinamento.

## 1. Pré-requisitos
Seu colega precisa ter instalado:
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)

## 2. Conectando ao Cluster
Ele precisa se autenticar na Azure e baixar as credenciais do Kubernetes:

```bash
# 1. Login na Azure
az login

# 2. Baixar credenciais do cluster (Peça para ele rodar isso)
az aks get-credentials --resource-group sky-aks-staging-rg --name sky-aks-staging
```

## 3. Cenário A: Usar o Ollama (Inferência / Chat)
Para testar prompts ou usar a API do Ollama que já está rodando:

```bash
# Redirecionar a porta do cluster para o computador dele
kubectl port-forward svc/ollama-service -n ollama 11434:11434
```
Agora ele pode usar no código dele `http://localhost:11434` como URL base.

## 4. Cenário B: Treinar um Modelo (Fine-Tuning)
O pod do Ollama é otimizado para *servir* modelos, não necessariamente para treinar (embora seja possível).
Para treinar, o ideal é criar um **Pod Temporário de Treino** que usa a mesma GPU.

Crie um arquivo `treino-gpu.yaml`:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: treino-dev-1
  namespace: ollama
spec:
  restartPolicy: Never
  containers:
  - name: pytorch
    image: pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime
    command: ["sleep", "infinity"] # Mantém o pod rodando para você entrar
    resources:
      limits:
        nvidia.com/gpu: 1 # Solicita a GPU T4
  nodeSelector:
    sky-poc-type: gpu
  tolerations:
  - key: "sku"
    operator: "Equal"
    value: "gpu"
    effect: "NoSchedule"
  - key: "kubernetes.azure.com/scalesetpriority"
    operator: "Equal"
    value: "spot"
    effect: "NoSchedule"
```

**Como usar:**
1. `kubectl apply -f treino-gpu.yaml`
2. `kubectl exec -it treino-dev-1 -n ollama -- /bin/bash`
3. Dentro do pod, rode seus scripts Python/PyTorch.
4. **IMPORTANTE**: Ao terminar, delete o pod (`kubectl delete pod treino-dev-1 -n ollama`) para liberar a GPU e o custo.
