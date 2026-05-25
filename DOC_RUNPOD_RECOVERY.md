📘 Guia Rápido — Ollama no RunPod (modo simples, sem Nginx)
🚀 PASSO 0 — Liberar a porta no RunPod (ANTES DE TUDO)

No Dashboard do RunPod:

Abra seu Pod

Vá em Networking / Exposed Ports

Clique em Add Port

Configure:

Campo	Valor
Container Port	19123
Protocol	HTTP

Salve

✅ Isso permite acessar o Ollama pela internet.

🔐 PASSO 1 — Conectar ao Pod via SSH
ssh r3j02klu1kl8w1-644110ca@ssh.runpod.io -i ~/.ssh/id_ed25519

📦 PASSO 2 — Instalar dependência obrigatória

O Ollama precisa do zstd:

apt-get update && apt-get install -y zstd

🤖 PASSO 3 — Instalar o Ollama
curl -fsSL https://ollama.com/install.sh | sh

▶️ PASSO 4 — Iniciar o Ollama na porta pública 19123
export OLLAMA_HOST=0.0.0.0:19123
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 5

🔍 PASSO 5 — Verificar se o serviço está rodando
pgrep -f "ollama serve"
ss -tlnp | grep 19123


Se aparecer um PID e a porta escutando → OK.

🧠 PASSO 6 — Baixar os modelos (um por vez)
ollama pull nomic-embed-text

ollama pull phi3:medium

ollama pull phi3:mini

🧪 PASSO 7 — Testar localmente dentro do Pod
curl http://127.0.0.1:19123/api/tags

🌍 PASSO 8 — Testar externamente (do seu computador)
curl https://r3j02klu1kl8w1-19123.proxy.runpod.net/api/tags


Se retornar a lista de modelos → 🎉 Ollama está acessível publicamente

📁 Logs do Ollama
cat /tmp/ollama.log

🔁 Quando o Pod reiniciar

Basta rodar de novo:

export OLLAMA_HOST=0.0.0.0:19123
nohup ollama serve > /tmp/ollama.log 2>&1 &
