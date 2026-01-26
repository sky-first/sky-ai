# 🔍 Script de Diagnóstico 404 - Nginx

## ⚠️ Pré-requisitos

Antes de executar o script, certifique-se de que:

1. **Você está conectado ao cluster Kubernetes correto:**
   ```bash
   # Verificar contexto atual
   kubectl config current-context
   
   # Se não estiver conectado ao AKS staging, conecte-se:
   az aks get-credentials \
     --resource-group <resource-group-name> \
     --name <aks-cluster-name> \
     --overwrite-existing
   ```

2. **Você tem permissões para acessar o namespace:**
   ```bash
   kubectl get namespace staging
   ```

## 🚀 Como Usar

### Uso Básico (valores padrão)
```bash
./scripts/diagnose-404-nginx.sh
```

Isso usa:
- Namespace: `staging`
- Host: `workspace-stg.skyfirstlabs.com`
- Service: `sky-fe-stg-common-app`

### Uso Personalizado
```bash
./scripts/diagnose-404-nginx.sh <namespace> <host>
```

Exemplo:
```bash
./scripts/diagnose-404-nginx.sh staging workspace-stg.skyfirstlabs.com
```

## 📋 O que o Script Verifica

1. **Conexão com o Cluster**
   - Verifica se o kubectl está configurado
   - Verifica se consegue conectar ao cluster

2. **Ingress**
   - Verifica se o Ingress existe para o host especificado
   - Mostra anotações do Ingress
   - Verifica regras de roteamento

3. **Service**
   - Verifica se o Service existe
   - Verifica se o Service tem endpoints (pods conectados)

4. **Pods**
   - Lista pods do frontend
   - Verifica status e saúde dos pods
   - Mostra logs recentes com erros

5. **Roteamento**
   - Verifica conflitos de paths
   - Verifica ordem de precedência

6. **Conectividade**
   - Mostra informações do Service
   - Fornece comandos para testar conectividade

## 🔧 Solução de Problemas

### Erro: "Não é possível conectar ao cluster Kubernetes"

**Causa:** O kubectl não está configurado ou não consegue se conectar ao cluster.

**Solução:**
```bash
# Verificar contexto
kubectl config current-context

# Conectar ao AKS
az login
az account set --subscription <subscription-id>
az aks get-credentials --resource-group <rg> --name <cluster> --overwrite-existing
```

### Erro: "Namespace não existe"

**Causa:** O namespace especificado não existe ou você não tem permissão.

**Solução:**
```bash
# Listar namespaces disponíveis
kubectl get namespaces

# Verificar permissões
kubectl auth can-i get pods -n staging
```

### Script trava ou não responde

**Causa:** O script pode estar aguardando resposta do kubectl.

**Solução:**
- Pressione `Ctrl+C` para cancelar
- Verifique sua conexão com o cluster
- Execute comandos kubectl manualmente para verificar

## 📝 Exemplo de Saída

```
==========================================
🔍 DIAGNÓSTICO: 404 Not Found - Nginx
==========================================

Namespace: staging
Host: workspace-stg.skyfirstlabs.com
Service: sky-fe-stg-common-app

==========================================
1️⃣  Verificando Ingress
==========================================

✅ Ingress encontrado para workspace-stg.skyfirstlabs.com

ℹ️  Detalhes do Ingress:
sky-fe-stg-common-app   nginx   workspace-stg.skyfirstlabs.com   20.xxx.xxx.xxx   80, 443   5d

ℹ️  Anotações do Ingress:
cert-manager.io/cluster-issuer: letsencrypt-prod
nginx.ingress.kubernetes.io/proxy-body-size: 50m
...

==========================================
2️⃣  Verificando Service
==========================================

✅ Service sky-fe-stg-common-app encontrado

ℹ️  Detalhes do Service:
NAME                      TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)   AGE
sky-fe-stg-common-app     ClusterIP   10.0.xxx.xxx   <none>        80/TCP    5d

✅ Service tem endpoints: 10.244.1.5 10.244.2.3

...
```

## 🔗 Ver Também

- [Documentação Completa](../docs/RESOLVER-404-NGINX-NEXTJS.md)
- [Configuração do Ingress](../gitops/bootstrap/staging/frontend.yaml)
