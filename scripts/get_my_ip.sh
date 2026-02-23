#!/bin/bash
# scripts/get_my_ip.sh
# Script para descobrir o IP público atual
# Útil para configurar allowed_ssh_ips no terraform.tfvars.prod

echo "Descobrindo seu IP público..."
echo ""

# Tentar múltiplos serviços para garantir que funciona
IP=""

if command -v curl &> /dev/null; then
  IP=$(curl -s https://api.ipify.org 2>/dev/null)
elif command -v wget &> /dev/null; then
  IP=$(wget -qO- https://api.ipify.org 2>/dev/null)
fi

if [ -z "$IP" ]; then
  echo "Erro: Não foi possível descobrir o IP público"
  echo "Tente manualmente: curl https://api.ipify.org"
  exit 1
fi

echo "[OK] Seu IP público é: $IP"
echo ""
echo "Adicione este IP ao arquivo terraform.tfvars.prod:"
echo ""
echo "  allowed_ssh_ips = ["
echo "    \"$IP/32\","
echo "    # Adicione outros IPs aqui se necessário"
echo "  ]"
echo ""
echo "Ou para múltiplos IPs:"
echo "  allowed_ssh_ips = [\"$IP/32\", \"OUTRO_IP/32\"]"
echo ""


