#!/bin/bash
set -e

echo "--- Iniciando Teste: 5000 VUs ---"
TARGET_VUS=5000 DURATION=5m k6 run scripts/load-test-flexible.js > k6_5000_results.log 2>&1

echo "--- Iniciando Teste: 10000 VUs ---"
TARGET_VUS=10000 DURATION=5m k6 run scripts/load-test-flexible.js > k6_10000_results.log 2>&1

echo "All high load tests completed."
