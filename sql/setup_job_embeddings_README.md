# Job Embeddings Table Setup

Before running the `02_generate_embeddings.py` script, you must create the `job_embeddings` table in your Lakebase Postgres database.

## Prerequisites

- Lakebase Postgres database is running
- pgvector extension is enabled
- job_postings table exists (created by `lakebase_schema.sql`)
- Jobs loaded via `01_ingest_jobs.py`

## Setup Instructions

1. Open `05_setup_job_embeddings_table.sql`
2. Replace `{{EMBEDDING_DIM}}` with the dimension for your chosen model:
   - Use `384` for all-MiniLM-L6-v2 (recommended for testing)
   - Use `1024` for databricks-gte-large-en (recommended for production)
3. Run the SQL script in your Lakebase database using psql or a Postgres client

## What Gets Created

**Table**: `job_embeddings`
- `id` (SERIAL, PRIMARY KEY)
- `job_id` (INTEGER, FK to job_postings.job_id)
- `chunk_index` (INTEGER) - Usually 0 for most job descriptions
- `chunk_text` (TEXT) - The job description text that was embedded
- `embedding` (VECTOR) - The vector embedding for semantic search
- `model_name` (TEXT) - Name of the model used
- `created_at` (TIMESTAMPTZ) - When the embedding was created

**Indexes**:
- HNSW index on embedding for fast vector similarity search
- Index on job_id for JOINs with job_postings
- Composite index on (job_id, chunk_index)

**Constraints**:
- UNIQUE(job_id, chunk_index) - Prevents duplicate embeddings
- Foreign key to job_postings with CASCADE delete

## Model Dimensions

- sentence-transformers/all-MiniLM-L6-v2: **384** (good for testing)
- sentence-transformers/all-mpnet-base-v2: 768
- BAAI/bge-small-en-v1.5: 384
- BAAI/bge-base-en-v1.5: 768
- BAAI/bge-large-en-v1.5: 1024
- databricks-gte-large-en: **1024** (recommended for production)

## Usage Example

After creating this table, you can run semantic searches like:

```sql
-- Find jobs similar to a query embedding
SELECT 
    jp.title,
    jp.company,
    jp.location,
    jp.salary_min,
    jp.salary_max,
    1 - (je.embedding <=> query_embedding) AS similarity
FROM job_embeddings je
JOIN job_postings jp ON je.job_id = jp.job_id
ORDER BY je.embedding <=> query_embedding
LIMIT 10;
```
