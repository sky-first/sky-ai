# Guia de Monitoramento Senior DevOps 🚀

Para elevar o nível de observabilidade da aplicação `sky-poc-backend` (FastAPI), é necessário instrumentar o código para expor as "Golden Signals" (Latência, Tráfego, Erros).

## 1. Instalação (No repositório do Backend)
Adicione a dependência:
```bash
pip install prometheus-fastapi-instrumentator
```

## 2. Implementação (main.py)
No arquivo onde você inicia o `FastAPI`, adicione:

```python
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()

# ... (suas rotas) ...

# Instrumentação Automática
@app.on_event("startup")
async def startup():
    Instrumentator().instrument(app).expose(app)
```

## 3. Resultado
Isso criará automaticamente o endpoint `/metrics` no backend.
O Prometheus passará a coletar:
* `http_requests_total`: Total de requisições (Tráfego).
* `http_request_duration_seconds`: Tempo de resposta (Latência).
* `http_requests_total{status="5xx"}`: Erros.

## 4. Integração com Logs (Loki)
Certifique-se que seus logs estão em JSON. O `Promtail` (já configurado na infra) lerá o `stdout` do container Docker e enviará para o Loki.
No Grafana, você poderá filtrar: `{container_name="ai_saas_backend_prod"} |= "error"`
