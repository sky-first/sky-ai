#!/bin/bash
# Script para corrigir problemas de infraestrutura

echo "============================================================"
echo "🔧 CORREÇÃO DE INFRAESTRUTURA"
echo "============================================================"

# 1. Verificar e matar processos antigos na porta 8000
echo ""
echo "1️⃣ Limpando processos antigos na porta 8000..."
PID=$(lsof -ti:8000 2>/dev/null)
if [ ! -z "$PID" ]; then
    echo "   Encerrando processo $PID..."
    kill -9 $PID 2>/dev/null
    sleep 2
    echo "   ✅ Processo encerrado"
else
    echo "   ✅ Nenhum processo encontrado"
fi

# 2. Verificar .env
echo ""
echo "2️⃣ Verificando arquivo .env..."
if [ -f ".env" ]; then
    echo "   ✅ Arquivo .env encontrado"
    if grep -q "DATABASE_URL" .env; then
        echo "   ✅ DATABASE_URL configurado"
    else
        echo "   ❌ DATABASE_URL não encontrado no .env"
    fi
else
    echo "   ❌ Arquivo .env não encontrado!"
    exit 1
fi

# 3. Testar conexão com banco
echo ""
echo "3️⃣ Testando conexão com banco..."
python3 scripts/test_db_connection.py 2>&1 | grep -E "✅|❌|Erro" | head -3

# 4. Iniciar API em background
echo ""
echo "4️⃣ Iniciando API..."
echo "   Executando: python3 run_api.py"
nohup python3 run_api.py > api.log 2>&1 &
API_PID=$!
echo "   API iniciada com PID: $API_PID"
echo "   Logs em: api.log"

# 5. Aguardar API iniciar
echo ""
echo "5️⃣ Aguardando API iniciar..."
for i in {1..10}; do
    sleep 1
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "   ✅ API está respondendo!"
        break
    fi
    echo "   Aguardando... ($i/10)"
done

# 6. Resumo
echo ""
echo "============================================================"
echo "📊 RESUMO"
echo "============================================================"
echo ""
echo "Para verificar status completo:"
echo "  python3 scripts/diagnose_infrastructure.py"
echo ""
echo "Para ver logs da API:"
echo "  tail -f api.log"
echo ""
echo "Para parar a API:"
echo "  kill $API_PID"
echo ""
