# Guia de Conexão ao Cluster AKS (Ollama)

## Especificações da GPU Disponível

- **GPU:** 1x NVIDIA Tesla T4 (16GB VRAM GDDR6)
- **CPU:** 4 vCPUs (AMD EPYC™ 7V12)
- **RAM:** 28 GB
- **Disco:** 180 GB SSD + 100 GB persistente (PVC)

**Modelos Suportados:** Llama3-8b, Phi3, Mistral, fine-tuning de modelos pequenos/médios

---

## Pré-requisitos Instalados

✅ **kubectl** - v1.34.1  
⏳ **Azure CLI** - Instalando (via brew)

---

## Quando Receber Acesso ao Cluster

### Passo 1: Conectar ao Cluster

Execute o script de conexão (só precisa fazer 1x):

```bash
./scripts/connect-aks.sh
```

Este script faz:
1. Login na Azure (`az login`)
2. Baixa credenciais do cluster
3. Verifica a conexão

### Passo 2: Iniciar Port-Forward

Em um **terminal separado**, execute:

```bash
./scripts/ollama-port-forward.sh
```

**Importante:** Mantenha este terminal aberto enquanto usar o Ollama.

### Passo 3: Configurar Aplicação

O Ollama ficará disponível em `http://localhost:11434`.

**Nenhuma mudança no código** é necessária - a URL já está configurada:

```python
# .env (já configurado)
OLLAMA_BASE_URL=http://localhost:11434
```

---

## Verificar se Funciona

Teste a conexão:

```bash
curl http://localhost:11434/api/tags
```

**Esperado:** Lista de modelos disponíveis no cluster.

---

## Comandos Úteis

### Ver pods do Ollama
```bash
kubectl get pods -n ollama
```

### Ver logs do Ollama
```bash
kubectl logs -n ollama -l app=ollama
```

### Verificar GPU
```bash
kubectl describe pod -n ollama -l app=ollama | grep -A 5 "nvidia.com/gpu"
```

---

## Troubleshooting

**Port-forward fechou?**  
Execute novamente: `./scripts/ollama-port-forward.sh`

**Erro de autenticação?**  
Execute: `az login` e repita `./scripts/connect-aks.sh`

**Modelos não aparecem?**  
Verifique se o Ollama está rodando:
```bash
kubectl get pods -n ollama
```

---

## Próximos Passos (Futuro)

### Treinar Modelos Custom

Se quiser fazer fine-tuning de modelos:

1. Criar pod de treino no cluster
2. Arquivo de configuração: `k8s/treino-gpu.yaml` (já preparado)
3. Executar treino usando a GPU T4

**Documentação completa:** Ver seção de treinamento quando necessário.

---

## Contato

**DevOps:** Para acesso ao cluster ou problemas de infraestrutura  
**Cluster:** `sky-aks-staging`  
**Namespace:** `ollama`
