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
echo "1.  Verificando Prometheus..."
echo ""
kubectl get deployment -n $MONITORING_NS -l app.kubernetes.io/name=prometheus || {
    echo "[ERROR] Prometheus não encontrado"
    exit 1
}

echo ""
echo "Prometheus Pods:"
kubectl get pods -n $MONITORING_NS -l app.kubernetes.io/name=prometheus -o wide || echo "[WARNING] Nenhum pod encontrado"

# 2. Verificar Grafana
echo ""
echo "2.  Verificando Grafana..."
echo ""
kubectl get deployment -n $MONITORING_NS -l app.kubernetes.io/name=grafana -o wide || echo "[WARNING] Grafana não encontrado"

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
    echo "[WARNING] Grafana Pod não encontrado"
fi

# 3. Verificar Loki
echo ""
echo "3.  Verificando Loki..."
echo ""
kubectl get deployment -n $MONITORING_NS -l app=loki -o wide || echo "[WARNING] Loki não encontrado"

echo ""
echo "Loki Pods:"
kubectl get pods -n $MONITORING_NS -l app=loki -o wide || echo "[WARNING] Nenhum pod encontrado"

# 4. Verificar Promtail
echo ""
echo "4.  Verificando Promtail (Log Collector)..."
echo ""
kubectl get daemonset -n $MONITORING_NS -l app=promtail -o wide || echo "[WARNING] Promtail não encontrado"

# 5. Verificar AlertManager
echo ""
echo "5.  Verificando AlertManager..."
echo ""
kubectl get statefulset -n $MONITORING_NS -l app.kubernetes.io/name=alertmanager -o wide || echo "[WARNING] AlertManager não encontrado"

# 6. Verificar ServiceMonitors
echo ""
echo "6.  Verificando ServiceMonitors..."
echo ""
kubectl get servicemonitors -n $PROD_NS || echo "[WARNING] Nenhum ServiceMonitor encontrado"

# 7. Verificar PrometheusRules
echo ""
echo "7.  Verificando PrometheusRules..."
echo ""
kubectl get prometheusrules -n $MONITORING_NS || echo "[WARNING] Nenhuma PrometheusRule encontrada"

# 8. Verificar storage
echo ""
echo "8.  Verificando Storage (PVCs)..."
echo ""
kubectl get pvc -n $MONITORING_NS || echo "[WARNING] Nenhum PVC encontrado"

# 9. Resumo
echo ""
echo "========================================="
echo "[OK] Validação de Monitoring Completa!"
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
