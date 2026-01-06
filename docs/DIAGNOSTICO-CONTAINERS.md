# 🔍 Diagnóstico de Containers - Deploy Caiu

## Status Atual

**Data:** $(date)  
**VM IP:** 20.86.142.1  
**Problema:** Frontend não está respondendo (ERR_CONNECTION_TIMED_OUT)

## Verificação Rápida

### 1. Verificar via HTTP (sem Azure CLI)

```bash
bash scripts/check-containers-simple.sh 20.86.142.1
```

### 2. Verificar via Azure CLI (requer login)

```bash
# Primeiro, faça login
az login

# Depois execute o diagnóstico completo
bash scripts/check-containers-status.sh poc-sky poc-sky 20.86.142.1
```

## Verificação Manual via Azure Portal

1. Acesse: https://portal.azure.com
2. Vá em: **Resource Groups** > **poc-sky**
3. Clique em: **Virtual Machines** > **poc-sky**
4. Clique em: **Run command** (no menu lateral)
5. Selecione: **RunShellScript**
6. Execute os seguintes comandos:

### Verificar containers rodando:
```bash
sudo docker ps
```

### Verificar status do docker compose:
```bash
cd /home/azureuser/projeto/sky-poc-infra
sudo docker compose ps
```

### Verificar containers parados:
```bash
sudo docker ps -a --filter "status=exited" --filter "status=dead"
```

### Verificar logs do proxy (crítico):
```bash
sudo docker compose logs proxy --tail=50
```

### Verificar logs do backend:
```bash
sudo docker compose logs backend --tail=50
```

### Verificar logs do frontend:
```bash
sudo docker compose logs frontend --tail=50
```

## Soluções Comuns

### 1. Reiniciar Containers

```bash
cd /home/azureuser/projeto/sky-poc-infra
sudo docker compose down
sudo docker compose up -d
```

### 2. Verificar se arquivo .env existe

```bash
cd /home/azureuser/projeto/sky-poc-infra
ls -la .env
cat .env | grep -E "(NEXT_PUBLIC_API_URL|CORS_ORIGINS)" || echo "Variáveis não encontradas"
```

### 3. Verificar recursos do sistema

```bash
# CPU e Memória
top -bn1 | head -5

# Disco
df -h /

# Memória
free -h
```

### 4. Verificar se serviços estão respondendo internamente

```bash
# PostgreSQL
sudo docker exec ai_saas_postgres_prod pg_isready -U postgres

# Redis
sudo docker exec ai_saas_redis_prod redis-cli ping

# Backend
curl http://localhost:8000/health || curl http://localhost:8000/api/v1/health

# Frontend
curl http://localhost:3000

# Proxy
curl http://localhost
```

### 5. Verificar Network Security Group (NSG)

O NSG pode estar bloqueando a porta 80. Verifique no Azure Portal:
- **Resource Groups** > **poc-sky** > **Network Security Groups**
- Verifique se há regra permitindo porta 80 de `0.0.0.0/0`

### 6. Verificar se VM está rodando

```bash
# Via Azure CLI
az vm show -g poc-sky -n poc-sky --show-details --query "powerState" -o tsv
```

## Comandos Úteis

### Ver todos os containers (incluindo parados):
```bash
sudo docker ps -a
```

### Ver uso de recursos dos containers:
```bash
sudo docker stats --no-stream
```

### Reiniciar um container específico:
```bash
sudo docker restart ai_saas_proxy
sudo docker restart ai_saas_backend_prod
sudo docker restart ai_saas_frontend_prod
```

### Ver logs em tempo real:
```bash
sudo docker compose logs -f
```

### Verificar health checks:
```bash
sudo docker inspect ai_saas_proxy --format='{{json .State.Health}}' | jq
```

## Containers Críticos

Os seguintes containers devem estar rodando:

1. ✅ `ai_saas_postgres_prod` - Banco de dados
2. ✅ `ai_saas_redis_prod` - Cache
3. ✅ `ai_saas_backend_prod` - API Backend
4. ✅ `ai_saas_frontend_prod` - Frontend Next.js
5. ✅ `ai_saas_proxy` - Nginx (CRÍTICO - expõe porta 80)

## Próximos Passos

1. Execute o diagnóstico completo usando os scripts acima
2. Verifique os logs dos containers que estão falhando
3. Se necessário, reinicie os containers
4. Verifique se o arquivo `.env` está configurado corretamente
5. Verifique se o NSG permite tráfego na porta 80

## Contato

Se o problema persistir após seguir estes passos, verifique:
- Logs do GitHub Actions do último deploy
- Status da VM no Azure Portal
- Alertas do Azure Monitor

