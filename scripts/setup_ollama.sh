#!/bin/bash
set -e

echo "🚀 Configurando Ollama e modelos locais..."

# Verificar se Ollama está instalado
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama não encontrado. Instale primeiro:"
    echo "   curl -fsSL https://ollama.com/install.sh | sh"
    exit 1
fi

# Baixar modelos base
echo "📥 Baixando modelos base..."
ollama pull phi3:mini
ollama pull sqlcoder:7b
ollama pull nomic-embed-text

# Criar modelo customizado SQLCoder
echo "🔧 Criando sqlcoder-sky (contexto 4096)..."
ollama create sqlcoder-sky -f - <<EOF
FROM sqlcoder:7b
PARAMETER num_ctx 4096
PARAMETER temperature 0
PARAMETER top_p 1
EOF

# Criar modelo customizado Phi-3
echo "🔧 Criando phi3-sky (contexto 4096)..."
ollama create phi3-sky -f - <<EOF
FROM phi3:mini
PARAMETER num_ctx 4096
PARAMETER temperature 0.3
EOF

echo "✅ Setup concluído!"
echo ""
echo "Modelos disponíveis:"
ollama list

echo ""
echo "Para testar:"
echo "  ollama run sqlcoder-sky"
echo "  ollama run phi3-sky"
