#!/bin/bash
set -e

# Aguarda qualquer processo k6 em execução terminar
echo "Verificando processos k6 ativos..."
while pgrep -x "k6" > /dev/null; do
    echo "[$(date)] k6 ainda em execução. Aguardando 15s..."
    sleep 15
done
echo "Processos anteriores concluídos. Iniciando Suite de Teste Escalada."

echo "--- Iniciando Teste: 2000 VUs ---"
TARGET_VUS=2000 DURATION=3m k6 run scripts/load-test-flexible.js > k6_2000_results.log 2>&1
echo "Concluído: 2000 VUs."

echo "--- Iniciando Teste: 5000 VUs ---"
TARGET_VUS=5000 DURATION=3m k6 run scripts/load-test-flexible.js > k6_5000_results.log 2>&1
echo "Concluído: 5000 VUs."

echo "--- Iniciando Teste: 10000 VUs ---"
TARGET_VUS=10000 DURATION=3m k6 run scripts/load-test-flexible.js > k6_10000_results.log 2>&1
echo "Concluído: 10000 VUs."

echo "Suite de Testes Finalizada com Sucesso."
