#!/bin/bash

echo "=== Monitoramento de Recursos do Sistema ==="
echo ""

echo "1. Uso de CPU:"
top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1
echo ""

echo "2. Uso de Memória:"
free -h
echo ""

echo "3. Uso de Disco:"
df -h | grep -E '^/dev|Filesystem'
echo ""

echo "4. Containers Docker (CPU e Memória):"
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
echo ""

echo "5. Processos consumindo mais CPU:"
ps aux --sort=-%cpu | head -6
echo ""

echo "6. Processos consumindo mais Memória:"
ps aux --sort=-%mem | head -6
echo ""

echo "7. Conexões de Rede Ativas:"
netstat -an | grep ESTABLISHED | wc -l
echo ""

echo "8. Load Average:"
uptime | awk -F'load average:' '{print $2}'
