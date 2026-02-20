FROM python:3.11-slim

WORKDIR /app

# Dependências de sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Criar usuário não root
RUN useradd -m -u 10001 appuser

# Instalar deps do AI service
COPY sky-poc-ai/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Código do AI service
COPY sky-poc-ai/ ./

# Ajustar permissões para o novo usuário
RUN chown -R appuser:appuser /app

# Definir o usuário para rodar a aplicação
USER appuser

EXPOSE 8001

# Produção: sem reload
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
