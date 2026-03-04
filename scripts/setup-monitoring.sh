#!/bin/bash
# scripts/setup-monitoring.sh
# Configura monitoramento básico (Prometheus + Grafana)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 Configurando monitoramento..."

# Criar diretório de configuração
mkdir -p "$PROJECT_DIR/monitoring"

# Criar prometheus.yml
cat > "$PROJECT_DIR/monitoring/prometheus.yml" <<'EOF'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'docker'
    static_configs:
      - targets: ['host.docker.internal:9323']
  
  - job_name: 'backend'
    static_configs:
      - targets: ['backend:8000']
  
  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres:5432']
EOF

echo "✅ Configuração do Prometheus criada"

# Criar docker-compose.monitoring.yml
cat > "$PROJECT_DIR/docker-compose.monitoring.yml" <<'EOF'
services:
  prometheus:
    image: prom/prometheus:latest
    container_name: ai_saas_prometheus
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    networks:
      - ai_saas_network
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: ai_saas_grafana
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
    networks:
      - ai_saas_network
    restart: unless-stopped
    depends_on:
      - prometheus

volumes:
  grafana_data:

networks:
  ai_saas_network:
    external: true
EOF

echo "✅ docker-compose.monitoring.yml criado"
echo ""
echo "Para iniciar o monitoramento:"
echo "  docker compose -f docker-compose.monitoring.yml up -d"
echo ""
echo "Acesse:"
echo "  Prometheus: http://localhost:9090"
echo "  Grafana: http://localhost:3001 (admin/${GRAFANA_PASSWORD:-admin})"

