#!/bin/bash
# ============================================================================
# Production Redeploy Script - Enterprise Grade
# ============================================================================

set -euo pipefail

readonly RESOURCE_GROUP="${RESOURCE_GROUP:-POC-SKY}"
readonly VM_NAME="${VM_NAME:-poc-sky}"
readonly PROJECT_DIR="${PROJECT_DIR:-/home/azureuser/projeto/sky-poc-infra}"

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

REMOTE_SCRIPT=$(cat <<'EOF'
#!/bin/bash
set -euo pipefail

readonly PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
readonly TIMEOUT_STARTUP=120
readonly TIMEOUT_HEALTHCHECK=60

log_info() { echo "[INFO] $*"; }
log_success() { echo "[SUCCESS] $*"; }
log_error() { echo "[ERROR] $*" >&2; }

cd "$PROJECT_DIR" || { log_error "Project directory not found: $PROJECT_DIR"; exit 1; }

log_info "Validating environment..."
[ -f .env ] || { log_error ".env file not found"; exit 1; }
[ -f docker-compose.yml ] || { log_error "docker-compose.yml not found"; exit 1; }

log_info "Detecting VM IP..."
VM_IP=$(curl -s -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | grep -oP '"publicIpAddress":"\K[^"]+' | head -1 || echo "20.86.142.1")
log_success "VM IP: $VM_IP"

log_info "Validating NEXT_PUBLIC_API_URL..."
EXPECTED_URL="http://${VM_IP}/api/v1"
if ! grep -q "^NEXT_PUBLIC_API_URL=${EXPECTED_URL}" .env; then
    sed -i "s|^NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=${EXPECTED_URL}|" .env
    log_success "NEXT_PUBLIC_API_URL updated"
fi

log_info "Validating Nginx configuration..."
if [ ! -d "certs" ] || [ ! -f "certs/fullchain.pem" ] || [ ! -f "certs/privkey.pem" ]; then
    if [ -f "docker/nginx/nginx.conf.http-only" ]; then
        cp "docker/nginx/nginx.conf.http-only" "docker/nginx/nginx.conf"
        log_success "Nginx configured for HTTP-only mode"
    fi
fi

log_info "Fixing Redis healthcheck configuration..."
if grep -q 'redis-cli -a "$$REDIS_PASSWORD" ping' docker-compose.yml || ! grep -A 3 "^  redis:" docker-compose.yml | grep -q "environment:"; then
    # Backup
    cp docker-compose.yml docker-compose.yml.backup.$(date +%Y%m%d_%H%M%S)
    
    # Use Python for reliable fix
    python3 << 'PYEOF'
import re

with open('docker-compose.yml', 'r') as f:
    content = f.read()

# Add environment if missing
if not re.search(r'  redis:.*?\n.*?environment:', content, re.DOTALL):
    content = re.sub(
        r'(  redis:.*?\n    container_name:.*?\n)',
        r'\1    environment:\n      REDIS_PASSWORD: ${REDIS_PASSWORD}\n',
        content,
        flags=re.DOTALL
    )

# Fix healthcheck
content = re.sub(
    r'redis-cli -a "\$\$REDIS_PASSWORD" ping[^"]*"',
    'redis-cli -a "$REDIS_PASSWORD" ping 2>/dev/null | grep -q PONG || exit 1"',
    content
)

# Fix command if needed
if 'sh -c' not in content or not re.search(r'redis:.*?sh -c', content, re.DOTALL):
    redis_match = re.search(r'(  redis:.*?)(    volumes:)', content, re.DOTALL)
    if redis_match:
        redis_block = redis_match.group(1)
        if 'sh -c' not in redis_block:
            new_command = '''    command: >
      sh -c "
        redis-server
        --requirepass $${REDIS_PASSWORD}
        --maxmemory 400mb
        --maxmemory-policy allkeys-lru
        --save ""
        --appendonly no
      "'''
            redis_block = re.sub(r'    command: >.*?--appendonly no', new_command, redis_block, flags=re.DOTALL)
            content = content[:redis_match.start()] + redis_block + redis_match.group(2) + content[redis_match.end():]

with open('docker-compose.yml', 'w') as f:
    f.write(content)
print("[SUCCESS] Redis configuration fixed")
PYEOF
    
    log_success "Redis healthcheck configuration fixed"
fi

log_info "Stopping services gracefully..."
docker compose stop backend frontend proxy worker beat 2>/dev/null || true
sleep 5

log_info "Starting infrastructure services..."
docker compose up -d postgres redis

log_info "Waiting for infrastructure to be healthy..."
MAX_WAIT=$TIMEOUT_HEALTHCHECK
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    POSTGRES_HEALTH=$(docker inspect ai_saas_postgres_prod --format '{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
    REDIS_HEALTH=$(docker inspect ai_saas_redis_prod --format '{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
    
    if [ "$POSTGRES_HEALTH" = "healthy" ] && [ "$REDIS_HEALTH" = "healthy" ]; then
        log_success "Infrastructure services are healthy"
        break
    fi
    
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        log_error "Infrastructure services did not become healthy within ${MAX_WAIT}s"
        log_error "Postgres: $POSTGRES_HEALTH, Redis: $REDIS_HEALTH"
        docker compose logs postgres --tail=20
        docker compose logs redis --tail=20
        exit 1
    fi
done

log_info "Running database migrations..."
docker compose up migrate
MIGRATE_EXIT=$?
if [ $MIGRATE_EXIT -ne 0 ]; then
    log_error "Migrations failed with exit code $MIGRATE_EXIT"
    docker compose logs migrate --tail=50
    exit 1
fi
log_success "Migrations completed"

log_info "Starting application services..."
docker compose up -d backend worker beat frontend proxy

log_info "Waiting for services to be ready (max ${TIMEOUT_STARTUP}s)..."
ELAPSED=0
MAX_WAIT=$TIMEOUT_STARTUP

while [ $ELAPSED -lt $MAX_WAIT ]; do
    BACKEND_HEALTH=$(docker inspect ai_saas_backend_prod --format '{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
    FRONTEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/ 2>/dev/null || echo "000")
    PROXY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/ 2>/dev/null || echo "000")
    
    if [ "$BACKEND_HEALTH" = "healthy" ] && [ "$FRONTEND_STATUS" = "200" ] && [ "$PROXY_STATUS" = "200" ]; then
        log_success "All services are ready"
        break
    fi
    
    sleep 3
    ELAPSED=$((ELAPSED + 3))
done

log_info "Performing final health check..."
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "backend|frontend|proxy|postgres|redis" || true

log_info "Testing endpoints..."
BACKEND_OK=false
if docker exec ai_saas_backend_prod python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" 2>/dev/null; then
    BACKEND_OK=true
    log_success "Backend /health endpoint OK"
else
    log_error "Backend /health endpoint failed"
fi

FRONTEND_OK=false
if [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/ 2>/dev/null || echo '000')" = "200" ]; then
    FRONTEND_OK=true
    log_success "Frontend endpoint OK"
else
    log_error "Frontend endpoint failed"
fi

PROXY_OK=false
if [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost/ 2>/dev/null || echo '000')" = "200" ]; then
    PROXY_OK=true
    log_success "Proxy endpoint OK"
else
    log_error "Proxy endpoint returned non-200 status"
fi

echo ""
echo "=========================================="
echo "DEPLOYMENT SUMMARY"
echo "=========================================="
echo "VM IP: $VM_IP"
echo "Backend: $([ "$BACKEND_OK" = "true" ] && echo "OK" || echo "FAILED")"
echo "Frontend: $([ "$FRONTEND_OK" = "true" ] && echo "OK" || echo "FAILED")"
echo "Proxy: $([ "$PROXY_OK" = "true" ] && echo "OK" || echo "WARNING")"
echo ""
echo "Access URL: http://$VM_IP"
echo "=========================================="

if [ "$BACKEND_OK" = "true" ] && [ "$FRONTEND_OK" = "true" ]; then
    exit 0
else
    exit 1
fi
EOF
)

log_info "Executing production redeploy on VM: $VM_NAME"

az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "$REMOTE_SCRIPT" "$PROJECT_DIR" \
  --output json | jq -r '.value[0].message' | sed 's/\\n/\n/g'

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log_success "Production redeploy completed successfully"
else
    log_error "Production redeploy failed with exit code $EXIT_CODE"
    exit $EXIT_CODE
fi

