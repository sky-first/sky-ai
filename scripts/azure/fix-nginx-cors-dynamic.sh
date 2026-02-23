#!/bin/bash
# Script para gerar e aplicar map de CORS dinamicamente baseado no IP da VM e CORS_ORIGINS
# Corrige o problema de CORS bloqueando requisições do IP da VM

set -eu

PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
cd "$PROJECT_DIR" || {
    if [ -d ~/projeto/sky-poc-infra ]; then
        cd ~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        cd ~/projeto/poc-deploy
    else
        echo "[ERROR] ERRO: Diretório do projeto não encontrado"
        exit 1
    fi
}

ENV_FILE=".env"
NGINX_CONF="docker/nginx/nginx.conf"
NGINX_HTTP_ONLY="docker/nginx/nginx.conf.http-only"
CORS_MAP_GENERATOR="docker/nginx/generate-cors-map.sh"

echo "=========================================="
echo " Configurando CORS Dinamicamente"
echo "=========================================="
echo ""

# Obter IP público da VM
VM_IP=$(curl -s -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | grep -oP '"publicIpAddress":"\K[^"]+' | head -1 || echo "")
if [ -z "$VM_IP" ]; then
    VM_IP=$(curl -s http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01 -H "Metadata:true" 2>/dev/null || echo "")
fi

if [ -z "$VM_IP" ]; then
    echo "[WARNING] Não foi possível obter IP da VM via Metadata API"
    echo "   Tentando obter do .env..."
    if [ -f "$ENV_FILE" ]; then
        VM_IP=$(grep -E "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" | sed 's|.*http://\([^/]*\).*|\1|' || echo "")
    fi
fi

if [ -z "$VM_IP" ]; then
    echo "[ERROR] ERRO: Não foi possível obter IP da VM"
    exit 1
fi

echo "[OK] IP da VM detectado: $VM_IP"
echo ""

# Carregar CORS_ORIGINS do .env se existir
CORS_ORIGINS=""
if [ -f "$ENV_FILE" ]; then
    CORS_ORIGINS=$(grep "^CORS_ORIGINS=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' || echo "")
fi

# Construir lista de origens: localhost + IP da VM + CORS_ORIGINS
ORIGINS_LIST="http://localhost,http://127.0.0.1,http://localhost:3000,http://127.0.0.1:3000"
ORIGINS_LIST="${ORIGINS_LIST},http://${VM_IP},https://${VM_IP}"

if [ -n "$CORS_ORIGINS" ]; then
    # Adicionar origens do .env (evitar duplicatas)
    IFS=',' read -ra ORIGINS_ARRAY <<< "$CORS_ORIGINS"
    for origin in "${ORIGINS_ARRAY[@]}"; do
        origin=$(echo "$origin" | tr -d '[:space:]')
        if [ -n "$origin" ] && [[ ! "$ORIGINS_LIST" =~ "$origin" ]]; then
            ORIGINS_LIST="${ORIGINS_LIST},${origin}"
        fi
    done
fi

echo "Origens CORS configuradas:"
echo "$ORIGINS_LIST" | tr ',' '\n' | sed 's/^/  - /'
echo ""

# Gerar map de CORS dinamicamente
if [ -f "$CORS_MAP_GENERATOR" ]; then
    chmod +x "$CORS_MAP_GENERATOR"
    CORS_MAP=$(bash "$CORS_MAP_GENERATOR" "$ORIGINS_LIST")
else
    echo "[WARNING] Script generate-cors-map.sh não encontrado, gerando map manualmente..."
    CORS_MAP="# Map gerado dinamicamente para validar origens CORS
map \$http_origin \$cors_origin {
    default \"\";
    \"~^http://localhost(:[0-9]+)?\$\" \$http_origin;
    \"~^http://127.0.0.1(:[0-9]+)?\$\" \$http_origin;"
    
    IFS=',' read -ra ORIGINS_ARRAY <<< "$ORIGINS_LIST"
    for origin in "${ORIGINS_ARRAY[@]}"; do
        origin=$(echo "$origin" | tr -d '[:space:]')
        if [ -n "$origin" ] && [[ "$origin" =~ ^https?:// ]]; then
            # Escapar para regex
            origin_escaped=$(echo "$origin" | sed 's/\./\\./g' | sed 's/\//\\\//g')
            if echo "$origin" | grep -qE ':[0-9]+$'; then
                CORS_MAP="${CORS_MAP}
    \"~^${origin_escaped}\$\" \"${origin}\";"
            else
                CORS_MAP="${CORS_MAP}
    \"~^${origin_escaped}(:[0-9]+)?\$\" \$http_origin;"
            fi
        fi
    done
    
    CORS_MAP="${CORS_MAP}
}"
fi

echo "Map de CORS gerado:"
echo "$CORS_MAP" | head -10
echo ""

# Aplicar map nos arquivos nginx.conf
for nginx_file in "$NGINX_CONF" "$NGINX_HTTP_ONLY"; do
    if [ -f "$nginx_file" ]; then
        echo "Atualizando $nginx_file..."
        
        # Fazer backup
        cp "$nginx_file" "${nginx_file}.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
        
        # Substituir map de CORS usando sed (mais robusto que awk para este caso)
        # Criar arquivo temporário com novo map
        TEMP_FILE=$(mktemp)
        
        # Processar arquivo linha por linha
        IN_MAP=0
        while IFS= read -r line; do
            if [[ "$line" =~ ^map\ \$http_origin\ \$cors_origin ]]; then
                # Início do map - substituir pelo novo
                echo "$CORS_MAP" >> "$TEMP_FILE"
                IN_MAP=1
            elif [ "$IN_MAP" -eq 1 ]; then
                # Dentro do map - pular linhas até encontrar }
                if [[ "$line" =~ ^} ]]; then
                    # Fim do map - já foi incluído no novo map, não adicionar esta linha
                    IN_MAP=0
                fi
                # Não adicionar linhas dentro do map antigo
            else
                # Fora do map - adicionar linha normalmente
                echo "$line" >> "$TEMP_FILE"
            fi
        done < "$nginx_file"
        
        # Substituir arquivo original
        mv "$TEMP_FILE" "$nginx_file"
        
        echo "[OK] $nginx_file atualizado"
    fi
done

echo ""
echo "=========================================="
echo "[OK] CORS Configurado Dinamicamente"
echo "=========================================="
echo ""

