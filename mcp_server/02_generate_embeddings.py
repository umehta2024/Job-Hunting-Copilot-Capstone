"""
Embeddings Generation Pipeline - Job Descriptions to Vectors

Reads job postings from Lakebase, generates semantic embeddings using 
sentence-transformers, and stores them for vector similarity search.

Usage:
    python 02_generate_embeddings.py
    
Or from a Databricks notebook:
    %run ./02_generate_embeddings
"""

import base64
import logging
from typing import List, Dict, Optional
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer
from databricks.sdk.runtime import dbutils

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Secrets configuration
SECRET_SCOPE = "job_hunting"
LAKEBASE_URL_KEY = "lakebase_url"

# Model configuration
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_DIMENSION = 384  # all-MiniLM-L6-v2 produces 384-dimensional vectors


class LakebaseClient:
    """Client for Lakebase Postgres database."""
    
    def __init__(self, connection_url: str):
        self.connection_url = connection_url
        self.conn = None
    
    def connect(self):
        """Establish connection to Lakebase."""
        try:
            self.conn = psycopg2.connect(self.connection_url)
            logger.info("✅ Connected to Lakebase")
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to Lakebase: {e}")
            raise
    
    def close(self):
        """Close the connection."""
        if self.conn:
            self.conn.close()
            logger.info("Lakebase connection closed")
    
    def get_jobs_without_embeddings(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Fetch job postings that don't have embeddings yet.
        
        Args:
            limit: Optional limit on number of jobs to fetch
        
        Returns:
            List of job dicts with job_id, title, company, description
        """
        query = """
            SELECT 
                jp.job_id,
                jp.title,
                jp.company,
                jp.location,
                jp.description,
                jp.salary_min,
                jp.salary_max
            FROM job_postings jp
            LEFT JOIN job_embeddings je ON jp.job_id = je.job_id
            WHERE je.job_id IS NULL
            AND jp.description IS NOT NULL
            AND length(jp.description) > 50
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(query)
                columns = [desc[0] for desc in cursor.description]
                results = cursor.fetchall()
                
                jobs = [dict(zip(columns, row)) for row in results]
                logger.info(f"Found {len(jobs)} jobs without embeddings")
                return jobs
                
        except psycopg2.Error as e:
            logger.error(f"Failed to fetch jobs: {e}")
            raise
    
    def insert_embeddings(self, embeddings: List[Dict]) -> int:
        """
        Insert embeddings into job_embeddings table.
        
        Args:
            embeddings: List of dicts with job_id, embedding, chunk_text, etc.
        
        Returns:
            Number of embeddings inserted
        """
        if not embeddings:
            return 0
        
        insert_sql = """
            INSERT INTO job_embeddings (
                job_id, chunk_index, chunk_text, embedding, model_name
            ) VALUES %s
            ON CONFLICT (job_id, chunk_index) DO NOTHING
        """
        
        # Prepare values
        values = [
            (
                emb["job_id"],
                emb["chunk_index"],
                emb["chunk_text"],
                emb["embedding"],
                emb["model_name"],
            )
            for emb in embeddings
        ]
        
        try:
            with self.conn.cursor() as cursor:
                execute_values(cursor, insert_sql, values, page_size=100)
                inserted = cursor.rowcount
                self.conn.commit()
                logger.info(f"✅ Inserted {inserted} embeddings")
                return inserted
                
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Failed to insert embeddings: {e}")
            raise


class EmbeddingGenerator:
    """Generate embeddings using sentence-transformers."""
    
    def __init__(self, model_name: str = DEFAULT_MODEL):
        logger.info(f"Loading model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name
        logger.info(f"✅ Model loaded (dimension: {self.model.get_sentence_embedding_dimension()})")
    
    def prepare_text(self, job: Dict) -> str:
        """
        Prepare job posting text for embedding.
        Combines title, company, location, and description.
        
        Args:
            job: Job dict from database
        
        Returns:
            Formatted text string
        """
        parts = []
        
        # Add title
        if job.get("title"):
            parts.append(f"Job Title: {job['title']}")
        
        # Add company
        if job.get("company"):
            parts.append(f"Company: {job['company']}")
        
        # Add location
        if job.get("location"):
            parts.append(f"Location: {job['location']}")
        
        # Add salary if available
        if job.get("salary_min") or job.get("salary_max"):
            sal_min = f"£{job['salary_min']:,.0f}" if job.get("salary_min") else "N/A"
            sal_max = f"£{job['salary_max']:,.0f}" if job.get("salary_max") else "N/A"
            parts.append(f"Salary: {sal_min} - {sal_max}")
        
        # Add description
        if job.get("description"):
            parts.append(f"\nDescription:\n{job['description']}")
        
        return "\n".join(parts)
    
    def generate_embeddings_batch(self, jobs: List[Dict]) -> List[Dict]:
        """
        Generate embeddings for a batch of jobs.
        
        Args:
            jobs: List of job dicts
        
        Returns:
            List of embedding dicts ready for insertion
        """
        if not jobs:
            return []
        
        # Prepare texts
        texts = [self.prepare_text(job) for job in jobs]
        job_ids = [job["job_id"] for job in jobs]
        
        # Generate embeddings in batch
        logger.info(f"Generating embeddings for {len(jobs)} jobs...")
        embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=True)
        
        # Prepare results
        results = []
        for job_id, text, embedding in zip(job_ids, texts, embeddings):
            results.append({
                "job_id": job_id,
                "chunk_index": 0,  # Most jobs fit in one chunk
                "chunk_text": text[:5000],  # Truncate for storage
                "embedding": embedding.tolist(),  # Convert numpy array to list
                "model_name": self.model_name,
            })
        
        return results


def get_secret(scope: str, key: str) -> str:
    """
    Retrieve a secret from Databricks secrets.
    Decodes base64 if the secret was stored encoded.
    """
    try:
        secret_bytes = dbutils.secrets.get(scope=scope, key=key)
        try:
            decoded = base64.b64decode(secret_bytes).decode("utf-8")
            # Try second decode if first result is still base64 (double-encoded)
            try:
                decoded = base64.b64decode(decoded).decode("utf-8")
            except:
                pass  # First decode was sufficient
            return decoded
        except Exception:
            return secret_bytes
    except Exception as e:
        logger.error(f"Failed to retrieve secret {scope}/{key}: {e}")
        raise


def generate_embeddings(
    batch_size: int = 50,
    limit: Optional[int] = None,
    model_name: str = DEFAULT_MODEL
) -> Dict:
    """
    Main function - generates embeddings for jobs and stores in Lakebase.
    
    Args:
        batch_size: Number of jobs to process in each batch
        limit: Optional limit on total jobs to process
        model_name: Sentence transformer model to use
    
    Returns:
        Summary dict with stats
    """
    logger.info("=" * 70)
    logger.info("Job Embeddings Generation Pipeline Starting")
    logger.info("=" * 70)
    
    # 1. Load secrets
    logger.info("Loading secrets...")
    lakebase_url = get_secret(SECRET_SCOPE, LAKEBASE_URL_KEY)
    
    # 2. Initialize clients
    lakebase = LakebaseClient(lakebase_url)
    lakebase.connect()
    
    embedding_gen = EmbeddingGenerator(model_name)
    
    total_processed = 0
    total_inserted = 0
    
    try:
        # 3. Fetch jobs without embeddings
        jobs = lakebase.get_jobs_without_embeddings(limit=limit)
        
        if not jobs:
            logger.info("No jobs need embeddings. All done!")
            return {
                "status": "success",
                "processed": 0,
                "inserted": 0,
                "message": "No new jobs to embed"
            }
        
        # 4. Process in batches
        for i in range(0, len(jobs), batch_size):
            batch = jobs[i:i + batch_size]
            logger.info(f"\nProcessing batch {i // batch_size + 1} ({len(batch)} jobs)...")
            
            # Generate embeddings
            embeddings = embedding_gen.generate_embeddings_batch(batch)
            
            # Insert into database
            inserted = lakebase.insert_embeddings(embeddings)
            
            total_processed += len(batch)
            total_inserted += inserted
        
        # 5. Summary
        logger.info("\n" + "=" * 70)
        logger.info("Embeddings Generation Complete!")
        logger.info("=" * 70)
        logger.info(f"Jobs processed: {total_processed}")
        logger.info(f"Embeddings inserted: {total_inserted}")
        
        return {
            "status": "success",
            "processed": total_processed,
            "inserted": total_inserted,
        }
        
    except Exception as e:
        logger.error(f"Embeddings generation failed: {e}")
        raise
    finally:
        lakebase.close()


if __name__ == "__main__":
    # Generate embeddings for all jobs without embeddings
    result = generate_embeddings(
        batch_size=50,
        limit=None,  # Process all jobs
        model_name=DEFAULT_MODEL
    )
    
    print("\n✅ Pipeline completed:")
    import json
    print(json.dumps(result, indent=2))
