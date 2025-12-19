-- Verificar se pgvector está disponível
SELECT * FROM pg_available_extensions WHERE name = 'vector';

-- Criar extensão vector
CREATE EXTENSION IF NOT EXISTS vector;

-- Criar tabela embeddings
CREATE TABLE IF NOT EXISTS embeddings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL,
  crew_id uuid NULL,
  user_id uuid NULL,
  table_metadata_id uuid NULL,
  document_id text NULL,
  embedding vector(3072) NOT NULL,
  text text NOT NULL,
  metadata jsonb NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Criar índices
CREATE INDEX IF NOT EXISTS idx_embeddings_space ON embeddings(space_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_crew ON embeddings(crew_id) WHERE crew_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_embeddings_user ON embeddings(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_embeddings_document ON embeddings(document_id) WHERE document_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_embeddings_table_metadata ON embeddings(table_metadata_id) WHERE table_metadata_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_embeddings_created_at ON embeddings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_embeddings_metadata_gin ON embeddings USING GIN (metadata);

-- Índice HNSW para buscas vetoriais
CREATE INDEX IF NOT EXISTS idx_embeddings_vector_hnsw ON embeddings 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

