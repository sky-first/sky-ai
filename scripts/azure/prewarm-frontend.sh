#!/usr/bin/env bash
# Pré-aquece rotas do frontend (Next dev) via Nginx para evitar 502 no primeiro acesso
# Uso: sudo bash scripts/azure/prewarm-frontend.sh [BASE_URL]

set -eu

BASE_URL="${1:-http://127.0.0.1}"
PATHS=("/login" "/dashboard")

echo "=========================================="
echo "🔥 Prewarm Frontend (Next.js via Nginx)"
echo "Base URL: $BASE_URL"
echo "=========================================="

for p in "${PATHS[@]}"; do
  echo ""
  echo "Prewarming: $p"
  ok=false
  for i in $(seq 1 24); do
    code="$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}${p}" || true)"
    echo "  try $i => HTTP $code"
    if [ "$code" = "200" ] || [ "$code" = "307" ] || [ "$code" = "302" ]; then
      ok=true
      break
    fi
    sleep 5
  done

  if [ "$ok" = "true" ]; then
    echo "✅ OK: $p"
  else
    echo "⚠️  AVISO: $p não estabilizou em tempo (pode estar compilando ainda)."
  fi
done

echo ""
echo "✅ Prewarm concluído"


