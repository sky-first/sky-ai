#!/usr/bin/env python3
import re

with open("docker-compose.yml", "r") as f:
    content = f.read()

# Buscar o bloco do backend
backend_match = re.search(r"(  backend:.*?)(    healthcheck:.*?start_period:.*?\n)(    networks:)", content, re.DOTALL)

if backend_match:
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
    
    with open("docker-compose.yml", "w") as f:
        f.write(content)
    print("SUCCESS")
else:
    if "python -c" in content and "urllib.request" in content:
        print("ALREADY_OK")
    else:
        print("NOT_FOUND")

