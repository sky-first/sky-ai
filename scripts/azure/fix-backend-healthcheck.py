#!/usr/bin/env python3
"""
Script para corrigir o healthcheck do backend no docker-compose.yml
Substitui curl por Python urllib
"""
import re
import shutil
from datetime import datetime

def fix_healthcheck():
    compose_file = "docker-compose.yml"
    
    # Backup
    backup_file = f"docker-compose.yml.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(compose_file, backup_file)
    print(f"[INFO] Backup criado: {backup_file}")
    
    # Ler arquivo
    with open(compose_file, "r") as f:
        content = f.read()
    
    # Verificar se tem curl no healthcheck
    if "curl" in content and "healthcheck" in content:
        # Substituir healthcheck que usa curl
        # Padrão: test: ["CMD-SHELL", "curl ..."]
        old_pattern = r'test:\s*\["CMD-SHELL",\s*"curl.*?health.*?"\]'
        new_test = '''test: ["CMD-SHELL", "python -c \\"import urllib.request; import sys; try: urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=5); sys.exit(0); except: pass; try: urllib.request.urlopen('http://localhost:8000/health', timeout=5); sys.exit(0); except: sys.exit(1)\\""]'''
        
        new_content = re.sub(old_pattern, new_test, content, flags=re.DOTALL)
        
        if new_content != content:
            with open(compose_file, "w") as f:
                f.write(new_content)
            print("[SUCCESS] Healthcheck corrigido para usar Python")
            return True
        else:
            print("[INFO] Não foi possível aplicar a correção")
            return False
    else:
        print("[INFO] Healthcheck já está usando Python ou não encontrado")
        return False

if __name__ == "__main__":
    fix_healthcheck()

