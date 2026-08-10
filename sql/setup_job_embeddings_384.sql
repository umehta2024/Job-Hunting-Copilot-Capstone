-- Setup script for job_embeddings table (384 dimensions)
-- Ready to run! Uses all-MiniLM-L6-v2 model (384 dimensions)
-- Run this against your Lakebase Postgres database

-- Enable pgvector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- Drop existing table if you want to recreate (optional - comment out if not needed)
-- DROP TABLE IF EXISTS job_embeddings CASCADE;

-- Create the job embeddings table
-- One embedding per job (entire job description embedded as single vector)
CREATE TABLE IF NOT EXISTS job_embeddings (
    embedding_id SERIAL PRIMARY KEY,
    job_id INTEGER UNIQUE NOT NULL,  -- UNIQUE: one embedding per job
    embedding vector(384),           -- 384-dim from all-MiniLM-L6-v2
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign key to job_postings
    FOREIGN KEY (job_id) REFERENCES job_postings(job_id) ON DELETE CASCADE
);

-- Create index on job_id for JOIN queries
CREATE INDEX IF NOT EXISTS idx_job_embeddings_job_id 
ON job_embeddings(job_id);

-- Create IVFFlat index for fast cosine similarity search
-- IVFFlat is the standard index type for pgvector
CREATE INDEX IF NOT EXISTS idx_job_embeddings_vector 
ON job_embeddings USING ivfflat (embedding vector_cosine_ops);

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
SELECT 'Schema matches actual implementation: one 384-dim embedding per job' AS verification;
