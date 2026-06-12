-- Sindio: Migration 006 — Document Chunks (keyword fallback for RAG)
-- Stores full-text chunks ingested by rag_ingestion.py alongside Qdrant vectors.

CREATE TABLE IF NOT EXISTS document_chunks (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_file       TEXT NOT NULL,
    page_num          INTEGER,
    chunk_index       INTEGER NOT NULL,
    chunk_text        TEXT NOT NULL,
    chunk_tokens      INTEGER,
    wards_mentioned   TEXT[],
    infrastructure_type TEXT,
    document_year     INTEGER,
    qdrant_point_id   TEXT,
    embedding_model   TEXT,
    metadata          JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Full-text search index for keyword-based retrieval fallback
CREATE INDEX IF NOT EXISTS idx_doc_chunks_fts
    ON document_chunks USING GIN (to_tsvector('english', chunk_text));

-- Lookup by source + position
CREATE INDEX IF NOT EXISTS idx_doc_chunks_source
    ON document_chunks (source_file, chunk_index);

-- Filter by infrastructure type
CREATE INDEX IF NOT EXISTS idx_doc_chunks_infra
    ON document_chunks (infrastructure_type)
    WHERE infrastructure_type IS NOT NULL;

-- Filter by ward
CREATE INDEX IF NOT EXISTS idx_doc_chunks_wards
    ON document_chunks USING GIN (wards_mentioned);

-- Qdrant point ID lookup (for sync/deletion)
CREATE INDEX IF NOT EXISTS idx_doc_chunks_qdrant
    ON document_chunks (qdrant_point_id)
    WHERE qdrant_point_id IS NOT NULL;
