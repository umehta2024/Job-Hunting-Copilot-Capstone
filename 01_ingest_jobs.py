"""
Job Ingestion Pipeline - Adzuna API to Lakebase

Fetches job postings from Adzuna API and loads them into Lakebase Postgres.
Handles duplicates using adzuna_id as a unique identifier.

Usage:
    python 01_ingest_jobs.py
    
Or from a Databricks notebook:
    %run ./01_ingest_jobs
"""

import base64
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import urlparse, parse_qs

import requests
import psycopg2
from psycopg2.extras import execute_values
from databricks.sdk.runtime import dbutils

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Secrets configuration
SECRET_SCOPE = "job_hunting"
APP_ID_KEY = "app_id"
APP_KEY_KEY = "app_key"
LAKEBASE_URL_KEY = "lakebase_url"


class AdzunaClient:
    """Client for Adzuna Job Search API."""
    
    def __init__(self, app_id: str, app_key: str, base_url: str = "https://api.adzuna.com/v1/api"):
        self.app_id = app_id
        self.app_key = app_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
    
    def search_jobs(
        self,
        country: str = "gb",
        what: Optional[str] = None,
        where: Optional[str] = None,
        results_per_page: int = 50,
        page: int = 1,
        sort_by: str = "date",
        max_days_old: Optional[int] = None
    ) -> Dict:
        """
        Search for jobs on Adzuna.
        
        Args:
            country: Country code (gb, us, au, etc.)
            what: Job title or keywords (e.g., "python developer")
            where: Location (e.g., "london")
            results_per_page: Number of results per page (max 50)
            page: Page number (starts at 1)
            sort_by: Sort order ("date", "relevance", "salary")
            max_days_old: Only return jobs posted within the last N days
        
        Returns:
            API response dict with 'results', 'count', '__job_count', etc.
        """
        endpoint = f"{self.base_url}/jobs/{country}/search/{page}"
        
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": results_per_page,
            "sort_by": sort_by,
        }
        
        if what:
            params["what"] = what
        if where:
            params["where"] = where
        if max_days_old:
            params["max_days_old"] = max_days_old
        
        try:
            resp = self.session.get(endpoint, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch jobs from Adzuna: {e}")
            return {}


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
    
    def insert_jobs(self, jobs: List[Dict]) -> tuple:
        """
        Insert jobs into the job_postings table.
        Uses ON CONFLICT to handle duplicates.
        
        Args:
            jobs: List of job dicts with keys matching table columns
        
        Returns:
            Tuple of (inserted_count, updated_count)
        """
        if not jobs:
            return 0, 0
        
        insert_sql = """
            INSERT INTO job_postings (
                adzuna_id, title, company, location, 
                salary_min, salary_max, description, url, posted_date
            ) VALUES %s
            ON CONFLICT (adzuna_id) 
            DO UPDATE SET
                title = EXCLUDED.title,
                company = EXCLUDED.company,
                location = EXCLUDED.location,
                salary_min = EXCLUDED.salary_min,
                salary_max = EXCLUDED.salary_max,
                description = EXCLUDED.description,
                url = EXCLUDED.url,
                posted_date = EXCLUDED.posted_date
            RETURNING (xmax = 0) AS inserted
        """
        
        # Prepare values for batch insert
        values = [
            (
                job.get("adzuna_id"),
                job.get("title"),
                job.get("company"),
                job.get("location"),
                job.get("salary_min"),
                job.get("salary_max"),
                job.get("description"),
                job.get("url"),
                job.get("posted_date"),
            )
            for job in jobs
        ]
        
        try:
            with self.conn.cursor() as cursor:
                # execute_values returns results
                execute_values(cursor, insert_sql, values, page_size=100, fetch=True)
                results = cursor.fetchall()
                
                # Count inserts vs updates
                inserted = sum(1 for r in results if r[0])  # xmax = 0 means new row
                updated = len(results) - inserted
                
                self.conn.commit()
                logger.info(f"✅ Inserted {inserted} new jobs, updated {updated} existing jobs")
                return inserted, updated
                
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Failed to insert jobs: {e}")
            raise


def get_secret(scope: str, key: str) -> str:
    """
    Retrieve a secret from Databricks secrets.
    Decodes base64 if the secret was stored encoded.
    """
    try:
        secret_bytes = dbutils.secrets.get(scope=scope, key=key)
        # Try to decode as base64 first (in case setup_secrets.py encoded it)
        try:
            return base64.b64decode(secret_bytes).decode("utf-8")
        except Exception:
            # If decoding fails, return as-is
            return secret_bytes
    except Exception as e:
        logger.error(f"Failed to retrieve secret {scope}/{key}: {e}")
        raise


def normalize_adzuna_job(job: Dict) -> Dict:
    """
    Normalize an Adzuna job result to match our schema.
    
    Args:
        job: Raw job dict from Adzuna API
    
    Returns:
        Normalized job dict ready for insertion
    """
    # Extract salary range
    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")
    
    # Parse posted date
    created = job.get("created")
    posted_date = None
    if created:
        try:
            # Adzuna returns ISO 8601 timestamp like "2024-01-15T10:30:00Z"
            posted_date = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            pass
    
    # Build location string
    location_parts = []
    if job.get("location", {}).get("display_name"):
        location_parts.append(job["location"]["display_name"])
    location = ", ".join(location_parts) if location_parts else None
    
    return {
        "adzuna_id": job.get("id"),
        "title": job.get("title"),
        "company": job.get("company", {}).get("display_name") if isinstance(job.get("company"), dict) else job.get("company"),
        "location": location,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "description": job.get("description"),
        "url": job.get("redirect_url"),
        "posted_date": posted_date,
    }


def ingest_jobs(
    country: str = "gb",
    what: Optional[str] = None,
    where: Optional[str] = None,
    max_pages: int = 5,
    max_days_old: int = 7
) -> Dict:
    """
    Main ingestion function - fetches jobs from Adzuna and loads into Lakebase.
    
    Args:
        country: Country code (gb, us, au, etc.)
        what: Job keywords (e.g., "python developer")
        where: Location (e.g., "london")
        max_pages: Maximum number of pages to fetch
        max_days_old: Only fetch jobs posted in last N days
    
    Returns:
        Summary dict with stats
    """
    logger.info("=" * 70)
    logger.info("Job Ingestion Pipeline Starting")
    logger.info("=" * 70)
    
    # 1. Load secrets
    logger.info("Loading secrets...")
    app_id = get_secret(SECRET_SCOPE, APP_ID_KEY)
    app_key = get_secret(SECRET_SCOPE, APP_KEY_KEY)
    lakebase_url = get_secret(SECRET_SCOPE, LAKEBASE_URL_KEY)
    
    # 2. Initialize clients
    adzuna = AdzunaClient(app_id, app_key)
    lakebase = LakebaseClient(lakebase_url)
    lakebase.connect()
    
    total_fetched = 0
    total_inserted = 0
    total_updated = 0
    
    try:
        # 3. Fetch jobs page by page
        for page in range(1, max_pages + 1):
            logger.info(f"\nFetching page {page}/{max_pages}...")
            
            response = adzuna.search_jobs(
                country=country,
                what=what,
                where=where,
                page=page,
                results_per_page=50,
                max_days_old=max_days_old,
            )
            
            results = response.get("results", [])
            if not results:
                logger.info("No more results, stopping.")
                break
            
            total_fetched += len(results)
            logger.info(f"  Fetched {len(results)} jobs")
            
            # 4. Normalize jobs
            normalized_jobs = [normalize_adzuna_job(job) for job in results]
            
            # 5. Insert into Lakebase
            inserted, updated = lakebase.insert_jobs(normalized_jobs)
            total_inserted += inserted
            total_updated += updated
        
        # 6. Summary
        logger.info("\n" + "=" * 70)
        logger.info("Ingestion Complete!")
        logger.info("=" * 70)
        logger.info(f"Total jobs fetched: {total_fetched}")
        logger.info(f"New jobs inserted: {total_inserted}")
        logger.info(f"Existing jobs updated: {total_updated}")
        
        return {
            "status": "success",
            "fetched": total_fetched,
            "inserted": total_inserted,
            "updated": total_updated,
        }
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise
    finally:
        lakebase.close()


if __name__ == "__main__":
    # Example: Fetch Python jobs in London from the last 7 days
    result = ingest_jobs(
        country="gb",
        what="python developer",
        where="london",
        max_pages=3,
        max_days_old=7
    )
    
    print("\n✅ Pipeline completed:")
    print(json.dumps(result, indent=2))
