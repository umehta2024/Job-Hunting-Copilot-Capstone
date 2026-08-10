#!/usr/bin/env python3
"""
Job Hunting MCP Server (FastMCP + HTTP)

Exposes job search, application tracking, and management functions via MCP protocol.
Deploy as a Databricks App for production use with proper user identity tracking.

Tools:
    - search_jobs(query, location, min_salary, top_k)
    - get_job_details(job_id)
    - save_job(job_id, notes)
    - update_application_status(job_id, status, notes)
    - add_interview_note(application_id, interview_date, interview_type, notes)
    - get_current_user()

Usage:
    python job_mcp_server.py
"""

import os
import logging
from typing import Dict, List
from contextvars import ContextVar

import psycopg2
from psycopg2.extras import RealDictCursor
import base64
from databricks.sdk import WorkspaceClient
from sentence_transformers import SentenceTransformer
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("job-hunting-mcp")

# Initialize Databricks client
w = WorkspaceClient()

# Context variable to store request headers for user identity
_request_context: ContextVar[dict] = ContextVar('request_context', default={})

def get_secret(scope: str, key: str) -> str:
    """Get secret from Databricks secrets."""
    try:
        secret_value = w.secrets.get_secret(scope=scope, key=key).value
        try:
            # Try first decode
            decoded = base64.b64decode(secret_value).decode("utf-8")
            # Try second decode if first result is still base64
            try:
                decoded = base64.b64decode(decoded).decode("utf-8")
            except:
                pass  # First decode was sufficient
            return decoded
        except:
            return secret_value
    except Exception as e:
        logger.error(f"Failed to get secret {scope}/{key}: {e}")
        raise

# Load resources
try:
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    lakebase_url = get_secret("job_hunting", "lakebase_url")
    logger.info("✅ Resources loaded: embedding model and Lakebase connection")
except Exception as e:
    logger.error(f"Failed to initialize: {e}")
    raise

def _get_user_id() -> int:
    """Get user ID from request headers or fallback to default."""
    headers = _request_context.get()
    forwarded_user = headers.get('x-forwarded-user')
    
    # In production: map email to user_id from a users table
    # For now: return 1 as default (single user)
    # TODO: Implement user lookup: SELECT user_id FROM users WHERE email = forwarded_user
    return 1

# Create FastMCP server
mcp = FastMCP("job-hunting")


# ===== JOB HUNTING TOOLS =====

@mcp.tool
def search_jobs(query: str, location: str = "", min_salary: int = 0, top_k: int = 5) -> dict:
    """
    Search for jobs using semantic similarity based on natural language query.
    
    Args:
        query: Natural language job search query (e.g. "Python backend developer")
        location: Optional location filter (e.g. "San Francisco")
        min_salary: Minimum salary in dollars (e.g. 100000)
        top_k: Number of results to return (default 5, max 20)
    
    Returns:
        Dict with query info and list of matching jobs sorted by similarity.
    """
    try:
        query_embedding = model.encode(query).tolist()
        
        sql = """
            SELECT 
                jp.job_id, jp.title, jp.company, jp.location, jp.description,
                jp.salary_min, jp.salary_max, jp.url,
                1 - (je.embedding <=> %s::vector) AS similarity
            FROM job_embeddings je
            JOIN job_postings jp ON je.job_id = jp.job_id
            WHERE 1=1
        """
        params = [query_embedding]
        
        if location:
            sql += " AND jp.location ILIKE %s"
            params.append(f"%{location}%")
        if min_salary > 0:
            sql += " AND (jp.salary_min >= %s OR jp.salary_max >= %s)"
            params.extend([min_salary, min_salary])
        
        sql += " ORDER BY je.embedding <=> %s::vector LIMIT %s"
        params.extend([query_embedding, min(top_k, 20)])
        
        conn = psycopg2.connect(lakebase_url)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                results = [dict(row) for row in cursor.fetchall()]
                return {
                    "status": "success",
                    "query": query,
                    "location": location or "any",
                    "min_salary": min_salary,
                    "count": len(results),
                    "jobs": results
                }
        finally:
            conn.close()
    except Exception as e:
        logger.exception("Search failed")
        return {"status": "error", "message": str(e)}


@mcp.tool
def get_job_details(job_id: int) -> dict:
    """
    Get complete details about a specific job posting.
    
    Args:
        job_id: The job ID to retrieve
    
    Returns:
        Dict with full job details including description, salary, requirements.
    """
    try:
        conn = psycopg2.connect(lakebase_url)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT job_id, title, company, location, description,
                           salary_min, salary_max, contract_type, url,
                           posted_date, created_at
                    FROM job_postings WHERE job_id = %s
                """, (job_id,))
                result = cursor.fetchone()
                if result:
                    return {"status": "success", "job": dict(result)}
                else:
                    return {"status": "not_found", "message": f"Job {job_id} not found"}
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"Failed to get job {job_id}")
        return {"status": "error", "message": str(e)}


@mcp.tool
def save_job(job_id: int, notes: str = "") -> dict:
    """
    Save a job to your favorites list.
    
    Args:
        job_id: The job ID to save
        notes: Optional notes about why you're saving this job
    
    Returns:
        Confirmation with saved_job_id and timestamp.
    """
    try:
        user_id = _get_user_id()
        conn = psycopg2.connect(lakebase_url)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO saved_jobs (user_id, job_id, notes)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, job_id) DO UPDATE SET
                        notes = EXCLUDED.notes,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING saved_job_id, created_at
                """, (user_id, job_id, notes or None))
                conn.commit()
                result = cursor.fetchone()
                return {
                    "status": "saved",
                    "saved_job_id": result['saved_job_id'],
                    "job_id": job_id,
                    "created_at": str(result['created_at'])
                }
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"Failed to save job {job_id}")
        return {"status": "error", "message": str(e)}


@mcp.tool
def update_application_status(job_id: int, status: str, notes: str = "") -> dict:
    """
    Track or update the status of a job application.
    
    Args:
        job_id: The job ID you're applying to
        status: Application status (applied, interviewing, offered, rejected, accepted, withdrawn)
        notes: Optional notes about the application
    
    Returns:
        Confirmation with application_id and updated timestamp.
    """
    valid_statuses = ['applied', 'interviewing', 'offered', 'rejected', 'accepted', 'withdrawn']
    if status not in valid_statuses:
        return {
            "status": "error",
            "message": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        }
    
    try:
        user_id = _get_user_id()
        conn = psycopg2.connect(lakebase_url)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO applications (user_id, job_id, status, notes)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, job_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        notes = EXCLUDED.notes,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING application_id, status, updated_at
                """, (user_id, job_id, status, notes or None))
                conn.commit()
                result = cursor.fetchone()
                return {
                    "status": "success",
                    "application_id": result['application_id'],
                    "job_id": job_id,
                    "application_status": result['status'],
                    "updated_at": str(result['updated_at'])
                }
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"Failed to update application for job {job_id}")
        return {"status": "error", "message": str(e)}


@mcp.tool
def add_interview_note(application_id: int, interview_date: str, interview_type: str, notes: str) -> dict:
    """
    Record notes about an interview.
    
    Args:
        application_id: The application ID (from update_application_status)
        interview_date: Interview date in YYYY-MM-DD format
        interview_type: Type of interview (phone, video, onsite, technical, behavioral)
        notes: Your interview notes and impressions
    
    Returns:
        Confirmation with note_id and timestamp.
    """
    valid_types = ['phone', 'video', 'onsite', 'technical', 'behavioral']
    if interview_type not in valid_types:
        return {
            "status": "error",
            "message": f"Invalid interview type. Must be one of: {', '.join(valid_types)}"
        }
    
    try:
        conn = psycopg2.connect(lakebase_url)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO interview_notes 
                        (application_id, interview_date, interview_type, notes)
                    VALUES (%s, %s, %s, %s)
                    RETURNING note_id, created_at
                """, (application_id, interview_date, interview_type, notes))
                conn.commit()
                result = cursor.fetchone()
                return {
                    "status": "note_added",
                    "note_id": result['note_id'],
                    "application_id": application_id,
                    "interview_date": interview_date,
                    "interview_type": interview_type,
                    "created_at": str(result['created_at'])
                }
        finally:
            conn.close()
    except Exception as e:
        logger.exception(f"Failed to add interview note for application {application_id}")
        return {"status": "error", "message": str(e)}


@mcp.tool
def get_current_user() -> dict:
    """
    Get information about the currently authenticated user.
    
    Returns:
        Dict with user_name (email), source, and forwarded headers.
    """
    try:
        headers = _request_context.get()
        forwarded_user = headers.get('x-forwarded-user')
        forwarded_email = headers.get('x-forwarded-email')
        
        if forwarded_user:
            return {
                "status": "success",
                "user_name": forwarded_user,
                "forwarded_email": forwarded_email,
                "source": "request_header"
            }
        
        # Fallback to service principal
        user = w.current_user.me()
        return {
            "status": "success",
            "user_name": user.user_name,
            "display_name": user.display_name,
            "source": "service_principal"
        }
    except Exception as e:
        logger.exception("Failed to get current user")
        return {"status": "error", "message": str(e)}


# ===== MIDDLEWARE =====

class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware to capture HTTP headers containing end-user identity."""
    async def dispatch(self, request: Request, call_next):
        headers = {
            'x-forwarded-user': request.headers.get('x-forwarded-user'),
            'x-forwarded-email': request.headers.get('x-forwarded-email'),
        }
        _request_context.set(headers)
        response = await call_next(request)
        return response


if __name__ == "__main__":
    # Add middleware for user identity tracking
    if hasattr(mcp, 'app') and mcp.app is not None:
        mcp.app.add_middleware(RequestContextMiddleware)
    
    # Run HTTP server (Databricks App or local)
    port = int(os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", 8000)))
    logger.info(f"🚀 Starting Job Hunting MCP Server on port {port}")
    logger.info("📦 Tools: search_jobs, get_job_details, save_job, update_application_status, add_interview_note, get_current_user")
    mcp.run(transport="http", host="0.0.0.0", port=port)
