-- Colección local E5 de 768 dimensiones; conserva intacta la tabla Gemini.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.vectores_rag_fae_local (
    id SERIAL PRIMARY KEY,
    chunk_id VARCHAR(50) NOT NULL,
    categoria_id VARCHAR(10) NOT NULL,
    seccion VARCHAR(255),
    fuente VARCHAR(255),
    page_content TEXT NOT NULL,
    metadata_json JSONB,
    embedding VECTOR(768)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_vectores_rag_fae_local_chunk_id
    ON public.vectores_rag_fae_local (chunk_id);
CREATE INDEX IF NOT EXISTS idx_vectores_rag_fae_local_hnsw
    ON public.vectores_rag_fae_local USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_vectores_rag_fae_local_texto
    ON public.vectores_rag_fae_local
    USING gin (to_tsvector('spanish', page_content));
