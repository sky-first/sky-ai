#!/bin/bash
# Solução rápida para problemas de infraestrutura

echo "🔧 CORREÇÃO RÁPIDA DE INFRAESTRUTURA"
echo "===================================="
echo ""

# 1. Verificar e corrigir API
echo "1️⃣ Verificando API..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✅ API já está rodando"
else
    echo "   ⚠️  API não está rodando"
    
    # Matar processos antigos
    PID=$(lsof -ti:8000 2>/dev/null)
    if [ ! -z "$PID" ]; then
        echo "   Encerrando processo antigo ($PID)..."
        kill -9 $PID 2>/dev/null
        sleep 1
    fi
    
    # Iniciar API
    echo "   Iniciando API..."
    cd "$(dirname "$0")/.."
    nohup python3 run_api.py > api.log 2>&1 &
    NEW_PID=$!
    echo "   API iniciada (PID: $NEW_PID)"
    echo "   Aguardando inicialização..."
    
    # Aguardar até 15 segundos
    for i in {1..15}; do
        sleep 1
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo "   ✅ API está respondendo!"
            break
        fi
        if [ $i -eq 15 ]; then
            echo "   ⚠️  API não respondeu após 15s"
            echo "   Verifique logs: tail -f api.log"
        fi
    done
fi

# 2. Verificar banco
echo ""
echo "2️⃣ Verificando banco de dados..."
python3 scripts/test_db_connection.py 2>&1 | grep -E "✅|❌|Erro" | head -2

# 3. Resumo
echo ""
echo "===================================="
echo "📊 RESUMO"
echo "===================================="
echo ""
echo "Para diagnóstico completo:"
echo "  python3 scripts/diagnose_infrastructure.py"
echo ""
echo "Para ver logs da API:"
echo "  tail -f api.log"
echo ""
echo "Para parar a API:"
echo "  kill \$(lsof -ti:8000)"
echo ""
