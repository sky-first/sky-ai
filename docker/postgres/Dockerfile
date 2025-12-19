# Usar imagem oficial do PostgreSQL 14
FROM postgres:14-alpine

# Instalar pgvector compilando do código-fonte
# A imagem pgvector/pgvector pode não ter o pgvector instalado corretamente
RUN apk add --no-cache \
    git \
    build-base \
    postgresql-dev \
    && cd /tmp \
    && git clone --branch v0.5.1 https://github.com/pgvector/pgvector.git \
    && cd pgvector \
    && make \
    && make install \
    && cd / \
    && rm -rf /tmp/pgvector \
    && apk del git build-base

# Copiar script de inicialização para criar extensão automaticamente
COPY docker/postgres/init-pgvector.sh /docker-entrypoint-initdb.d/
RUN chmod +x /docker-entrypoint-initdb.d/init-pgvector.sh
