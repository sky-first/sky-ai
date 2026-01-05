#!/bin/sh
# Script para gerar map de CORS dinamicamente a partir de CORS_ORIGINS
# Uso: ./generate-cors-map.sh <CORS_ORIGINS> > /tmp/cors-map.conf
# Exemplo: ./generate-cors-map.sh "http://example.com,https://example.com,http://localhost:3000"

set -eu

CORS_ORIGINS="${1:-http://localhost:3000,http://localhost}"

echo "# Map gerado dinamicamente para validar origens CORS"
echo "map \$http_origin \$cors_origin {"
echo "    default \"\";"

# Processar cada origem da lista
IFS=','
for origin in $CORS_ORIGINS; do
    # Remover espaços em branco
    origin=$(echo "$origin" | tr -d '[:space:]')
    
    # Escapar caracteres especiais para regex do nginx
    origin_escaped=$(echo "$origin" | sed 's/\./\\./g' | sed 's/\//\\\//g')
    
    # Gerar entrada no map
    # Aceita origem exata ou com porta opcional
    if echo "$origin" | grep -qE '^https?://[^:]+:[0-9]+$'; then
        # Tem porta específica
        echo "    \"~^${origin_escaped}\$\" \"${origin}\";"
    else
        # Sem porta ou porta opcional
        echo "    \"~^${origin_escaped}(:[0-9]+)?\$\" \$http_origin;"
    fi
done

echo "}"

