#!/bin/bash
# Script para corrigir o healthcheck do backend na VM
# Substitui curl por Python urllib

set -euo pipefail

cd /home/azureuser/projeto/sky-poc-infra || exit 1

# Backup
cp docker-compose.yml docker-compose.yml.backup.$(date +%Y%m%d_%H%M%S)

# Usar Python para fazer a substituição correta
python3 << 'PYEOF'
import re
import yaml

with open("docker-compose.yml", "r") as f:
    content = f.read()

# Buscar o bloco do backend
backend_match = re.search(r"(  backend:.*?)(    healthcheck:.*?start_period:.*?\n)(    networks:)", content, re.DOTALL)

if backend_match:
    # Healthcheck correto com formato YAML válido
    new_healthcheck = """    healthcheck:
      # Usar Python ao invés de curl (curl não está instalado no container)
      # Python urllib já está disponível no container do backend
      test: ["CMD-SHELL", "python -c \"import urllib.request; import sys; try: urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=5); sys.exit(0); except: pass; try: urllib.request.urlopen('http://localhost:8000/health', timeout=5); sys.exit(0); except: sys.exit(1)\""]
      interval: 20s
      timeout: 10s
      retries: 5
      start_period: 30s
"""
    
    new_content = backend_match.group(1) + new_healthcheck + backend_match.group(3)
    content = content[:backend_match.start()] + new_content + content[backend_match.end():]
    
    # Validar YAML antes de salvar
    try:
        yaml.safe_load(content)
        with open("docker-compose.yml", "w") as f:
            f.write(content)
        print("SUCCESS: Healthcheck corrigido e YAML validado")
    except yaml.YAMLError as e:
        print(f"ERROR: YAML inválido após correção: {e}")
        exit(1)
else:
    print("INFO: Padrão não encontrado ou já está correto")
    # Verificar se já está usando Python
    if 'python -c' in content and 'urllib.request' in content:
        print("INFO: Healthcheck já está usando Python")
    else:
        print("WARNING: Não foi possível encontrar o healthcheck do backend")
        exit(1)
PYEOF

# Validar novamente com docker compose
if docker compose config > /dev/null 2>&1; then
    echo "[OK] YAML válido!"
    exit 0
else
    echo "[ERROR] YAML ainda inválido"
    docker compose config 2>&1 | head -20
    exit 1
fi

