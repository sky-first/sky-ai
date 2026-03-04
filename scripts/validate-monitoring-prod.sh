#!/bin/bash

# Script: Validar Monitoring Stack em Produção
# Purpose: Verificar Prometheus, Grafana, Loki e AlertManager
# Usage: ./scripts/validate-monitoring-prod.sh

set -e

MONITORING_NS="monitoring"
PROD_NS="prod"

echo "📊 Validando Stack de Monitoramento"
echo ""

# 1. Verificar Prometheus
echo "1️⃣  Verificando Prometheus..."
echo ""
kubectl get deployment -n $MONITORING_NS -l app.kubernetes.io/name=prometheus || {
    echo "❌ Prometheus não encontrado"
    exit 1
}

echo ""
echo "Prometheus Pods:"
kubectl get pods -n $MONITORING_NS -l app.kubernetes.io/name=prometheus -o wide || echo "⚠️  Nenhum pod encontrado"

# 2. Verificar Grafana
echo ""
echo "2️⃣  Verificando Grafana..."
echo ""
kubectl get deployment -n $MONITORING_NS -l app.kubernetes.io/name=grafana -o wide || echo "⚠️  Grafana não encontrado"

echo ""
echo "Grafana acesso:"
GRAFANA_POD=$(kubectl get pods -n $MONITORING_NS -l app.kubernetes.io/name=grafana -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$GRAFANA_POD" ]; then
    echo "Pod: $GRAFANA_POD"
    echo ""
    echo "Para acessar localmente:"
    echo "  kubectl port-forward pod/$GRAFANA_POD 3000:3000 -n $MONITORING_NS"
    echo "  http://localhost:3000 (admin/prom-operator)"
else
    echo "⚠️  Grafana Pod não encontrado"
fi

# 3. Verificar Loki
echo ""
echo "3️⃣  Verificando Loki..."
echo ""
kubectl get deployment -n $MONITORING_NS -l app=loki -o wide || echo "⚠️  Loki não encontrado"

echo ""
echo "Loki Pods:"
kubectl get pods -n $MONITORING_NS -l app=loki -o wide || echo "⚠️  Nenhum pod encontrado"

# 4. Verificar Promtail
echo ""
echo "4️⃣  Verificando Promtail (Log Collector)..."
echo ""
kubectl get daemonset -n $MONITORING_NS -l app=promtail -o wide || echo "⚠️  Promtail não encontrado"

# 5. Verificar AlertManager
echo ""
echo "5️⃣  Verificando AlertManager..."
echo ""
kubectl get statefulset -n $MONITORING_NS -l app.kubernetes.io/name=alertmanager -o wide || echo "⚠️  AlertManager não encontrado"

# 6. Verificar ServiceMonitors
echo ""
echo "6️⃣  Verificando ServiceMonitors..."
echo ""
kubectl get servicemonitors -n $PROD_NS || echo "⚠️  Nenhum ServiceMonitor encontrado"

# 7. Verificar PrometheusRules
echo ""
echo "7️⃣  Verificando PrometheusRules..."
echo ""
kubectl get prometheusrules -n $MONITORING_NS || echo "⚠️  Nenhuma PrometheusRule encontrada"

# 8. Verificar storage
echo ""
echo "8️⃣  Verificando Storage (PVCs)..."
echo ""
kubectl get pvc -n $MONITORING_NS || echo "⚠️  Nenhum PVC encontrado"

# 9. Resumo
echo ""
echo "========================================="
echo "✅ Validação de Monitoring Completa!"
echo "========================================="
echo ""
echo "Acessos:"
echo "  Prometheus: kubectl port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090 -n $MONITORING_NS"
echo "  Grafana:    kubectl port-forward svc/prometheus-grafana 3000:80 -n $MONITORING_NS"
echo "  Loki:       kubectl port-forward svc/loki 3100:3100 -n $MONITORING_NS"
echo ""
echo "URLs locais:"
echo "  http://localhost:9090 (Prometheus)"
echo "  http://localhost:3000 (Grafana)"
