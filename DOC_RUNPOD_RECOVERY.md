# Configuração Simples do Ollama no RunPod

## Novo Pod
- **Pod ID**: `r3j02klu1kl8w1`
- **SSH**: `ssh r3j02klu1kl8w1-644110ca@ssh.runpod.io -i ~/.ssh/id_ed25519`
- **URL Pública**: `https://r3j02klu1kl8w1-19123.proxy.runpod.net`

## Setup Rápido (SEM Nginx!)

Como seu pod é Ubuntu/Debian (padrão RunPod), roda:


apt-get update && apt-get install -y zstd
```bash

# 1. Instalar Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Iniciar Ollama na porta 19123
export OLLAMA_HOST=0.0.0.0:19123
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 5

# 3. Baixar modelos
ollama pull nomic-embed-text
ollama pull phi3:medium
ollama pull phi3:mini

# 4. Verificar
ss -tlnp | grep 19123
curl http://127.0.0.1:19123/api/tags
```

## Teste Externo

```bash
curl https://r3j02klu1kl8w1-19123.proxy.runpod.net/api/tags
```

## Atualizar .env Local

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=https://r3j02klu1kl8w1-19123.proxy.runpod.net
```

## Recuperação Após Reinício

```bash
export OLLAMA_HOST=0.0.0.0:19123
nohup ollama serve > /tmp/ollama.log 2>&1 &
```
