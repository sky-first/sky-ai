# Usar imagem com pgvector já incluído (evita build de toolchain/clang)
FROM pgvector/pgvector:pg14

# trivy:ignore:DS-0002 (Official database image drops privileges internally)

# Copiar script de inicialização para criar extensão automaticamente
COPY docker/postgres/init-pgvector.sh /docker-entrypoint-initdb.d/
RUN chmod +x /docker-entrypoint-initdb.d/init-pgvector.sh
