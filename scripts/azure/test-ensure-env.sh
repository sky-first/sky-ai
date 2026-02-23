#!/bin/bash
# Script de teste rápido para ensure-complete-env.sh
# Testa se o script não trava

echo " Testando ensure-complete-env.sh..."
echo ""

# Executar script em background com timeout manual
(
    ./scripts/azure/ensure-complete-env.sh . 2>&1
    echo "[OK] Script concluído"
) &
SCRIPT_PID=$!

# Aguardar no máximo 10 segundos
for i in {1..10}; do
    if ! kill -0 $SCRIPT_PID 2>/dev/null; then
        # Processo terminou
        wait $SCRIPT_PID
        exit $?
    fi
    sleep 1
    echo -n "."
done

# Se ainda estiver rodando, matar
if kill -0 $SCRIPT_PID 2>/dev/null; then
    echo ""
    echo "[ERROR] Script travou após 10 segundos"
    kill $SCRIPT_PID 2>/dev/null
    exit 1
fi

wait $SCRIPT_PID
exit $?

