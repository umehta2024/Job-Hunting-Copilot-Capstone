-- Setup script for job_embeddings table (384 dimensions)
-- Ready to run! Uses all-MiniLM-L6-v2 model (384 dimensions)
-- Run this against your Lakebase Postgres database

-- Enable pgvector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the job embeddings table
CREATE TABLE IF NOT EXISTS job_embeddings (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    model_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Foreign key to job_postings
    CONSTRAINT fk_job_posting
        FOREIGN KEY (job_id)
        REFERENCES job_postings(job_id)
        ON DELETE CASCADE,
    
    -- Ensure one embedding per job (most jobs fit in one chunk)
    UNIQUE(job_id, chunk_index)
);

-- Create HNSW index for fast cosine similarity search
-- HNSW is more accurate than IVFFlat and recommended for most use cases
CREATE INDEX IF NOT EXISTS idx_job_embeddings_embedding
ON job_embeddings
USING hnsw (embedding vector_cosine_ops);

-- Create index on job_id for JOIN queries
CREATE INDEX IF NOT EXISTS idx_job_embeddings_job_id
ON job_embeddings (job_id);

-- Create index on chunk_index for ordering within a job
CREATE INDEX IF NOT EXISTS idx_job_embeddings_chunk_index
ON job_embeddings (job_id, chunk_index);

-- Verify the table was created
SELECT 
    table_name,
    column_name,
    data_type,
    udt_name
FROM information_schema.columns
WHERE table_name = 'job_embeddings'
ORDER BY ordinal_position;

-- Success message
SELECT 'job_embeddings table created successfully! Ready for embedding ingestion.' AS status;
