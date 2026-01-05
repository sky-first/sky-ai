#!/bin/bash
# Garante que .env tenha todas as variáveis necessárias
# Usado no deploy para garantir configuração completa

# Garantir que está sendo executado com bash (não zsh ou sh)
if [ -z "$BASH_VERSION" ]; then
    echo "❌ ERRO: Este script deve ser executado com bash"
    echo "💡 Execute: bash $0"
    exit 1
fi

set -eu

# Detectar diretório do script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Se um diretório foi passado como argumento, usar ele
# Caso contrário, tentar detectar automaticamente
if [ -n "${1:-}" ]; then
    PROJECT_DIR="$1"
else
    # Tentar detectar automaticamente:
    # 1. Diretório atual se contém env.example
    # 2. Diretório do script (assumindo que script está em scripts/azure/)
    # 3. Caminhos comuns na VM
    if [ -f "env.example" ]; then
        PROJECT_DIR="$(pwd)"
    elif [ -f "$PROJECT_ROOT/env.example" ]; then
        PROJECT_DIR="$PROJECT_ROOT"
    elif [ -d "/home/azureuser/projeto/sky-poc-infra" ]; then
        PROJECT_DIR="/home/azureuser/projeto/sky-poc-infra"
    elif [ -d ~/projeto/sky-poc-infra ]; then
        PROJECT_DIR=~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        PROJECT_DIR=~/projeto/poc-deploy
    else
        # Fallback: usar diretório do script
        PROJECT_DIR="$PROJECT_ROOT"
    fi
fi

# Mudar para o diretório do projeto
cd "$PROJECT_DIR" || {
    echo "❌ ERRO: Não foi possível acessar o diretório: $PROJECT_DIR"
    echo "💡 Dica: Execute o script do diretório sky-poc-infra ou passe o caminho como argumento"
    exit 1
}

# Verificar que estamos no diretório correto
if [ ! -f "env.example" ]; then
    echo "❌ ERRO: Arquivo env.example não encontrado em: $PROJECT_DIR"
    echo "💡 Certifique-se de estar no diretório sky-poc-infra"
    exit 1
fi

ENV_FILE=".env"
ENV_EXAMPLE="env.example"

# Obter IP público da VM
# Nota: Em ambiente local (não Azure), isso falhará silenciosamente (esperado)
VM_IP=""
if command -v curl >/dev/null 2>&1; then
    # Tentar obter via Azure Metadata API (formato direto)
    # CRÍTICO: Adicionar timeout para evitar travamento em ambiente local
    VM_IP=$(curl -s --max-time 2 --connect-timeout 1 http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01 -H "Metadata:true" 2>/dev/null || echo "")
    
    # Se não funcionou, tentar formato JSON (compatível com BSD grep do macOS)
    if [ -z "$VM_IP" ]; then
        METADATA_JSON=$(curl -s --max-time 2 --connect-timeout 1 -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" 2>/dev/null || echo "")
        if [ -n "$METADATA_JSON" ]; then
            # Usar sed ou awk para extrair IP (compatível com BSD)
            VM_IP=$(echo "$METADATA_JSON" | grep -o '"publicIpAddress":"[^"]*"' | sed 's/.*"publicIpAddress":"\([^"]*\)".*/\1/' | head -1)
        fi
    fi
fi

# Se ainda não conseguiu, tentar obter IP da interface de rede (apenas para referência local)
if [ -z "$VM_IP" ]; then
    # Em ambiente local, não há IP público da VM, então deixar vazio
    VM_IP=""
fi

# Criar .env se não existir
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_EXAMPLE" ]; then
        echo "📋 Criando .env a partir de $ENV_EXAMPLE..."
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        # Tentar definir permissões adequadas (pode falhar em alguns ambientes, mas não é crítico)
        chmod 600 "$ENV_FILE" 2>/dev/null || chmod 644 "$ENV_FILE" 2>/dev/null || true
    else
        echo "❌ ERRO: $ENV_EXAMPLE não encontrado"
        exit 1
    fi
fi

# Verificar se arquivo é legível
# Nota: Permissões 600 (rw-------) são OK se o usuário atual for o proprietário
if [ ! -r "$ENV_FILE" ]; then
    # Tentar verificar se somos o proprietário
    if [ -O "$ENV_FILE" ] 2>/dev/null; then
        # Somos o proprietário, então podemos ler mesmo com 600
        echo "ℹ️  Arquivo $ENV_FILE tem permissões restritivas, mas você é o proprietário (OK)"
    else
        echo "⚠️  AVISO: Arquivo $ENV_FILE não é legível. Tentando corrigir permissões..."
        # Tentar corrigir permissões
        if chmod 644 "$ENV_FILE" 2>/dev/null || chmod 600 "$ENV_FILE" 2>/dev/null; then
            echo "✅ Permissões corrigidas"
        else
            echo "⚠️  Não foi possível corrigir permissões automaticamente"
            echo "💡 Se o script falhar, execute manualmente:"
            echo "   chmod 644 $ENV_FILE"
        fi
    fi
fi

# Função para gerar senha segura
generate_password() {
    python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || \
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-32
}

# Função para gerar chave JWT
generate_jwt_secret() {
    python3 -c "import secrets; print(secrets.token_urlsafe(64))" 2>/dev/null || \
    openssl rand -base64 64 | tr -d "=+/" | cut -c1-64
}

# Função para sed in-place (compatível com macOS e Linux)
sed_inplace() {
    local file="$1"
    shift
    # macOS requer extensão, Linux não
    if sed --version >/dev/null 2>&1; then
        # Linux (GNU sed)
        sed -i "$@" "$file"
    else
        # macOS (BSD sed)
        sed -i '' "$@" "$file"
    fi
}

# Função para garantir variável existe
ensure_var() {
    local var_name=$1
    local default_value=$2
    local is_secret=${3:-false}
    
    # Verificar se arquivo existe
    if [ ! -f "$ENV_FILE" ]; then
        echo "⚠️  Arquivo $ENV_FILE não existe. Tentando criar..."
        if [ -f "$ENV_EXAMPLE" ]; then
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            chmod 600 "$ENV_FILE" 2>/dev/null || true
        else
            echo "❌ ERRO: Não foi possível criar $ENV_FILE (env.example não encontrado)"
            return 1
        fi
    fi
    
    # Tentar ler o arquivo (pode falhar se não tiver permissão, mas continuamos)
    if ! grep -q "^${var_name}=" "$ENV_FILE" 2>/dev/null; then
        if [ -n "$default_value" ]; then
            # Tentar escrever no arquivo (pode falhar em ambiente restrito)
            if echo "${var_name}=${default_value}" >> "$ENV_FILE" 2>/dev/null; then
                if [ "$is_secret" = "true" ]; then
                    echo "✅ ${var_name} adicionado (gerado)"
                else
                    echo "✅ ${var_name} adicionado: ${default_value}"
                fi
            else
                echo "⚠️  Não foi possível adicionar ${var_name} (sem permissão de escrita)"
                echo "   Valor sugerido: ${var_name}=${default_value}"
            fi
        else
            echo "⚠️  ${var_name} não encontrado e sem valor padrão"
        fi
    else
        # Verificar se valor está vazio ou é placeholder
        local current_value=$(grep "^${var_name}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || echo "")
        if [ -z "$current_value" ] || [[ "$current_value" == *"secure_password"* ]] || [[ "$current_value" == *"here"* ]]; then
            if [ -n "$default_value" ]; then
                # Tentar atualizar (pode falhar em ambiente restrito)
                if sed_inplace "$ENV_FILE" "s|^${var_name}=.*|${var_name}=${default_value}|" 2>/dev/null; then
                    if [ "$is_secret" = "true" ]; then
                        echo "✅ ${var_name} atualizado (gerado)"
                    else
                        echo "✅ ${var_name} atualizado: ${default_value}"
                    fi
                else
                    echo "⚠️  Não foi possível atualizar ${var_name} (sem permissão de escrita)"
                    echo "   Valor sugerido: ${var_name}=${default_value}"
                fi
            fi
        fi
    fi
}

echo "=========================================="
echo "🔧 Garantindo .env Completo"
echo "=========================================="
echo ""

# Variáveis de banco de dados
ensure_var "POSTGRES_USER" "postgres"
ensure_var "POSTGRES_PASSWORD" "$(generate_password)" true
ensure_var "POSTGRES_DB" "ai_saas_db"
ensure_var "POSTGRES_PORT" "5433"

# Redis
ensure_var "REDIS_PASSWORD" "$(generate_password)" true

# JWT e Encryption
ensure_var "JWT_SECRET_KEY" "$(generate_jwt_secret)" true
ensure_var "ENCRYPTION_KEY" "$(generate_password)" true

# Database URL - CRÍTICO: usar asyncpg
if ! grep -q "^DATABASE_URL=" "$ENV_FILE"; then
    POSTGRES_USER_VAL=$(grep "^POSTGRES_USER=" "$ENV_FILE" | cut -d'=' -f2)
    POSTGRES_PASSWORD_VAL=$(grep "^POSTGRES_PASSWORD=" "$ENV_FILE" | cut -d'=' -f2)
    POSTGRES_DB_VAL=$(grep "^POSTGRES_DB=" "$ENV_FILE" | cut -d'=' -f2)
    echo "DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER_VAL}:${POSTGRES_PASSWORD_VAL}@postgres:5432/${POSTGRES_DB_VAL}" >> "$ENV_FILE"
    echo "✅ DATABASE_URL adicionado (asyncpg)"
else
    # Corrigir se estiver usando psycopg2
    if grep -q "postgresql+psycopg2://" "$ENV_FILE"; then
        sed_inplace "$ENV_FILE" "s|postgresql+psycopg2://|postgresql+asyncpg://|g"
        sed_inplace "$ENV_FILE" "s|?sslmode=require||g"
        echo "✅ DATABASE_URL corrigido para asyncpg"
    fi
fi

# Redis URL
if ! grep -q "^REDIS_URL=" "$ENV_FILE"; then
    REDIS_PASSWORD_VAL=$(grep "^REDIS_PASSWORD=" "$ENV_FILE" | cut -d'=' -f2)
    echo "REDIS_URL=redis://:${REDIS_PASSWORD_VAL}@redis:6379/0" >> "$ENV_FILE"
    echo "✅ REDIS_URL adicionado"
fi

# Celery
if ! grep -q "^CELERY_BROKER_URL=" "$ENV_FILE"; then
    REDIS_PASSWORD_VAL=$(grep "^REDIS_PASSWORD=" "$ENV_FILE" | cut -d'=' -f2)
    echo "CELERY_BROKER_URL=redis://:${REDIS_PASSWORD_VAL}@redis:6379/1" >> "$ENV_FILE"
    echo "CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD_VAL}@redis:6379/2" >> "$ENV_FILE"
    echo "✅ CELERY URLs adicionadas"
fi

# Frontend - NEXT_PUBLIC_API_URL
# CRÍTICO: Garantir que NEXT_PUBLIC_API_URL sempre seja configurado corretamente
if [ -z "$VM_IP" ]; then
    # Tentar métodos alternativos para obter IP
    echo "Tentando obter IP da VM via métodos alternativos..."
    
    # Método 1: Azure Metadata API (formato alternativo)
    VM_IP=$(curl -s --max-time 2 --connect-timeout 1 http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01 -H "Metadata:true" 2>/dev/null || echo "")
    
    # Método 2: Extrair de NEXT_PUBLIC_API_URL se já existir
    if [ -z "$VM_IP" ] && [ -f "$ENV_FILE" ]; then
        EXISTING_URL=$(grep "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' || echo "")
        if [ -n "$EXISTING_URL" ]; then
            VM_IP=$(echo "$EXISTING_URL" | sed 's|.*http://\([^/]*\).*|\1|' | sed 's|.*https://\([^/]*\).*|\1|')
            if [ "$VM_IP" = "localhost" ] || [ "$VM_IP" = "127.0.0.1" ]; then
                VM_IP=""
            fi
        fi
    fi
    
    # Método 3: Tentar obter via hostname ou interface de rede
    if [ -z "$VM_IP" ]; then
        VM_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")
        # Verificar se é IP privado (não usar IP privado)
        if echo "$VM_IP" | grep -qE "^10\.|^172\.(1[6-9]|2[0-9]|3[01])\.|^192\.168\."; then
            VM_IP=""
        fi
    fi
fi

# NEXT_PUBLIC_API_URL - DEVOPS: Configuração crítica para frontend acessar backend
# Estratégia: Preferir path relativo (/api/v1) que funciona através do Nginx
# Se path relativo não estiver configurado, usar IP completo como fallback
if ! grep -q "^NEXT_PUBLIC_API_URL=" "$ENV_FILE"; then
    # Não configurado: usar path relativo (melhor prática)
    echo "NEXT_PUBLIC_API_URL=/api/v1" >> "$ENV_FILE"
    echo "✅ NEXT_PUBLIC_API_URL adicionado: /api/v1 (path relativo - recomendado)"
else
    CURRENT_URL=$(grep "^NEXT_PUBLIC_API_URL=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "")
    
    # Detectar e corrigir problemas comuns
    NEEDS_FIX=false
    FIX_REASON=""
    
    # Problema 1: localhost:8000 (não funciona em containers)
    if echo "$CURRENT_URL" | grep -qE "localhost:8000|127\.0\.0\.1:8000"; then
        NEEDS_FIX=true
        FIX_REASON="URL usa localhost:8000 (não funciona em containers Docker)"
    fi
    
    # Problema 2: IP antigo/incorreto (se temos IP atual)
    if [ -n "$VM_IP" ] && echo "$CURRENT_URL" | grep -qE "http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+"; then
        URL_IP=$(echo "$CURRENT_URL" | grep -oE "http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | sed 's|http://||')
        if [ "$URL_IP" != "$VM_IP" ]; then
            NEEDS_FIX=true
            FIX_REASON="IP desatualizado ($URL_IP -> $VM_IP)"
        fi
    fi
    
    if [ "$NEEDS_FIX" = "true" ]; then
        # Corrigir: SEMPRE preferir path relativo quando VM_IP não estiver disponível
        # Path relativo funciona em qualquer ambiente (local, staging, produção)
        if echo "$CURRENT_URL" | grep -qE "^/api/v1$"; then
            # Já está usando path relativo - manter
            echo "✅ NEXT_PUBLIC_API_URL já usa path relativo: $CURRENT_URL"
        elif [ -z "$VM_IP" ]; then
            # Sem IP da VM: usar path relativo (melhor prática e funciona sempre)
            sed_inplace "$ENV_FILE" "s|^NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=/api/v1|"
            echo "✅ NEXT_PUBLIC_API_URL corrigido para path relativo: /api/v1 ($FIX_REASON)"
        elif [ -n "$VM_IP" ] && echo "$CURRENT_URL" | grep -qE "http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+"; then
            # Tem IP da VM e URL já usa IP: atualizar para IP correto
            sed_inplace "$ENV_FILE" "s|^NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=http://${VM_IP}/api/v1|"
            echo "✅ NEXT_PUBLIC_API_URL corrigido: http://${VM_IP}/api/v1 ($FIX_REASON)"
        else
            # Qualquer outro caso: usar path relativo (mais seguro)
            sed_inplace "$ENV_FILE" "s|^NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=/api/v1|"
            echo "✅ NEXT_PUBLIC_API_URL corrigido para path relativo: /api/v1 ($FIX_REASON)"
        fi
    else
        # Verificar se está usando path relativo (recomendado)
        if echo "$CURRENT_URL" | grep -qE "^/api/v1$"; then
            echo "✅ NEXT_PUBLIC_API_URL configurado corretamente (path relativo): $CURRENT_URL"
        elif [ -n "$VM_IP" ] && echo "$CURRENT_URL" | grep -q "$VM_IP"; then
            echo "✅ NEXT_PUBLIC_API_URL configurado corretamente (IP completo): $CURRENT_URL"
        else
            echo "⚠️  NEXT_PUBLIC_API_URL: $CURRENT_URL (verifique se está correto)"
        fi
    fi
fi

# CORS
ensure_var "CORS_ORIGINS" "http://${VM_IP:-localhost:3000},https://${VM_IP:-localhost:3000}"

# Debug e Environment
ensure_var "DEBUG" "false"
ensure_var "ENVIRONMENT" "production"
ensure_var "NODE_ENV" "production"

# Sentry (opcional)
if ! grep -q "^SENTRY_DSN=" "$ENV_FILE"; then
    echo "SENTRY_DSN=" >> "$ENV_FILE"
fi

# ============================================
# AI Engine (sky-poc-ai)
# ============================================
# DEVOPS:
# - AI_SERVICE_URL é interno do docker compose (não expor publicamente)
# - OPENAI_API_KEY pode vir via Key Vault / GitHub Secrets (não commitar)
# - Se OPENAI_API_KEY estiver preenchido, habilitamos AI_SERVICE_TYPE=real
ensure_var "AI_SERVICE_URL" "http://ai:8001"
ensure_var "AI_SERVICE_TYPE" "mock"

# Garantir que a variável exista no .env mesmo que vazia (para documentação/clareza)
if ! grep -q "^OPENAI_API_KEY=" "$ENV_FILE" 2>/dev/null; then
    echo "OPENAI_API_KEY=" >> "$ENV_FILE" 2>/dev/null || true
    echo "✅ OPENAI_API_KEY adicionado (vazio)"
fi

# Se a chave estiver presente, ativar modo real
OPENAI_VAL=$(grep "^OPENAI_API_KEY=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2- | tr -d ' ' | tr -d '"' | tr -d "'" || echo "")
AI_TYPE_VAL=$(grep "^AI_SERVICE_TYPE=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2- | tr -d ' ' | tr -d '"' | tr -d "'" || echo "mock")
if [ -n "$OPENAI_VAL" ] && [ "${AI_TYPE_VAL}" != "real" ]; then
    if sed_inplace "$ENV_FILE" "s|^AI_SERVICE_TYPE=.*|AI_SERVICE_TYPE=real|" 2>/dev/null; then
        echo "✅ AI_SERVICE_TYPE habilitado: real (OPENAI_API_KEY presente)"
    fi
fi

# Ajustar permissões
chmod 600 "$ENV_FILE"

echo ""
echo "=========================================="
echo "✅ .env Completo e Validado"
echo "=========================================="
echo ""
echo "Variáveis configuradas:"
grep -E "^(POSTGRES_|REDIS_|JWT_|ENCRYPTION_|DATABASE_|CELERY_|NEXT_PUBLIC_|CORS_|DEBUG|ENVIRONMENT|NODE_ENV|AI_SERVICE_|OPENAI_API_KEY)=" "$ENV_FILE" | sed 's/=.*/=***/' | head -20
echo ""

