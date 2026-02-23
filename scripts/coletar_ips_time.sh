#!/bin/bash
# scripts/coletar_ips_time.sh
# Script para coletar IPs de todos os membros do time
# Cada membro executa e envia o resultado

echo "=== Coletor de IPs do Time ==="
echo ""
echo "Este script gera um arquivo com seu IP para compartilhar com o time"
echo ""

# Descobrir IP
IP=$(curl -s https://api.ipify.org 2>/dev/null || echo "ERRO")

if [ "$IP" = "ERRO" ] || [ -z "$IP" ]; then
  echo "[ERROR] Erro ao descobrir IP"
  exit 1
fi

# Criar arquivo com informações
OUTPUT_FILE="meu_ip_$(whoami)_$(date +%Y%m%d).txt"

cat > "$OUTPUT_FILE" <<EOF
=== IP Público para SSH ===
Nome: $(whoami)
Data: $(date)
IP: $IP/32

Adicione ao terraform.tfvars.prod:
  "$IP/32",  # $(whoami)

EOF

echo "[OK] Arquivo criado: $OUTPUT_FILE"
echo ""
echo "Conteúdo:"
cat "$OUTPUT_FILE"
echo ""
echo " Compartilhe este arquivo com o time DevOps"
echo "   (via Slack, email, ou repositório privado)"

