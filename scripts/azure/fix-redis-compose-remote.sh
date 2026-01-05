#!/bin/bash
# Fix Redis configuration in docker-compose.yml on VM
# Enterprise-grade: Simple and reliable

set -euo pipefail

readonly RESOURCE_GROUP="${RESOURCE_GROUP:-POC-SKY}"
readonly VM_NAME="${VM_NAME:-poc-sky}"

FIX_SCRIPT=$(cat <<'EOF'
#!/bin/bash
set -euo pipefail

PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
cd "$PROJECT_DIR" || exit 1

echo "[INFO] Fixing Redis configuration in docker-compose.yml..."

# Backup
cp docker-compose.yml docker-compose.yml.backup.$(date +%Y%m%d_%H%M%S)

# Use Python for reliable YAML manipulation
python3 << 'PYTHON_SCRIPT'
import re
import sys

with open('docker-compose.yml', 'r') as f:
    content = f.read()

# Check if fix is needed
if 'redis-cli -a "$$REDIS_PASSWORD" ping' in content:
    # Add environment if not present
    if 'environment:\n      REDIS_PASSWORD:' not in content or not re.search(r'redis:.*\n.*environment:', content, re.DOTALL):
        # Find redis: block and add environment after container_name
        pattern = r'(  redis:.*?\n    container_name:.*?\n)'
        replacement = r'\1    environment:\n      REDIS_PASSWORD: ${REDIS_PASSWORD}\n'
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Fix healthcheck
    content = re.sub(
        r'redis-cli -a "\$\$REDIS_PASSWORD" ping[^"]*"',
        'redis-cli -a "$REDIS_PASSWORD" ping 2>/dev/null | grep -q PONG || exit 1"',
        content
    )
    
    # Fix command to use sh -c if needed
    if 'sh -c' not in content or not re.search(r'redis:.*sh -c', content, re.DOTALL):
        # Replace command block
        redis_block = re.search(r'  redis:.*?(?=  [a-z]|volumes:)', content, re.DOTALL)
        if redis_block:
            block = redis_block.group(0)
            if 'sh -c' not in block:
                # Replace command
                new_command = '''    command: >
      sh -c "
        redis-server
        --requirepass $${REDIS_PASSWORD}
        --maxmemory 400mb
        --maxmemory-policy allkeys-lru
        --save ""
        --appendonly no
      "'''
                block = re.sub(r'    command: >.*?--appendonly no', new_command, block, flags=re.DOTALL)
                content = content[:redis_block.start()] + block + content[redis_block.end():]
    
    with open('docker-compose.yml', 'w') as f:
        f.write(content)
    print("[SUCCESS] Redis configuration fixed")
else:
    print("[INFO] Redis configuration already correct")
PYTHON_SCRIPT

echo "[SUCCESS] Configuration updated"
EOF
)

az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "$FIX_SCRIPT" "$PROJECT_DIR" \
  --output json | jq -r '.value[0].message' | sed 's/\\n/\n/g'

