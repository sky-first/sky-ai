set -eu

cd /home/azureuser/projeto/sky-poc-infra || cd ~/projeto/sky-poc-infra

echo "--- patch docker-compose.yml (frontend memory + NODE_OPTIONS) ---"
python3 - <<'PY'
from pathlib import Path
import re

path = Path("docker-compose.yml")
s = path.read_text(encoding="utf-8")

if "  frontend:" not in s:
    raise SystemExit("ERRO: serviço frontend não encontrado em docker-compose.yml")

# Garantir NODE_OPTIONS no environment do frontend, e aumentar limites de memória
lines = s.splitlines(True)
out = []
in_frontend = False
node_opts_inserted = False
mem_limit_set = False
mem_reservation_set = False

for line in lines:
    if line.startswith("  frontend:"):
        in_frontend = True
        out.append(line)
        continue

    # Sai do bloco do frontend ao encontrar próximo service (mesma indentação)
    if in_frontend and re.match(r"^  [a-zA-Z0-9_-]+:\s*$", line):
        # Antes de sair, se não existiam limites, adiciona-os logo antes
        if not mem_limit_set:
            out.append("    # Limites de recursos\n")
            out.append("    mem_limit: 2g\n")
            out.append("    mem_reservation: 1g\n")
        in_frontend = False

    if in_frontend:
        if re.match(r"^\s*mem_limit:\s*", line):
            out.append("    mem_limit: 2g\n")
            mem_limit_set = True
            continue
        if re.match(r"^\s*mem_reservation:\s*", line):
            out.append("    mem_reservation: 1g\n")
            mem_reservation_set = True
            continue

        # Inserir NODE_OPTIONS no environment do frontend (antes do NEXT_PUBLIC_API_URL)
        if line.strip() == "environment:":
            out.append(line)
            continue
        if (not node_opts_inserted) and line.startswith("      NEXT_PUBLIC_API_URL:"):
            out.append("      NODE_OPTIONS: --max-old-space-size=1536\n")
            node_opts_inserted = True
            out.append(line)
            continue

    out.append(line)

text = "".join(out)
path.write_text(text, encoding="utf-8")
print("OK: docker-compose.yml atualizado")
PY

echo "--- recreate frontend ---"
sudo docker compose up -d --force-recreate frontend

echo "--- frontend state ---"
sudo docker inspect ai_saas_frontend_prod --format 'RestartCount={{.RestartCount}} OOMKilled={{.State.OOMKilled}} Status={{.State.Status}} StartedAt={{.State.StartedAt}}' || true

echo "--- warmup dashboard (best effort) ---"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/login || true
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/dashboard || true


