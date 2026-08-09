"""
Databricks Job Hunting Copilot App:
- Serves a Flask API for job search
- Reads/writes to Lakebase (Databricks-managed Postgres) via lakebase.py
- Provides semantic job search using vector embeddings (NO LLM needed!)

Run locally:
    python app.py
Deploy as a Databricks App using app.yaml.
"""

import json as _json
import logging
import os

from databricks.sdk import WorkspaceClient
from flask import Flask, jsonify, render_template, request
from sentence_transformers import SentenceTransformer

import lakebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job-hunting-app")

app = Flask(__name__)
_w = WorkspaceClient()

JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE_NAME", "job_postings")
EMBEDDINGS_TABLE_NAME = os.environ.get("EMBEDDINGS_TABLE_NAME", "job_embeddings")
SAVED_JOBS_TABLE_NAME = os.environ.get("SAVED_JOBS_TABLE_NAME", "saved_jobs")
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Load embedding model once at module level for semantic search
logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}...")
_embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
logger.info("Embedding model loaded")


def ensure_tables():
    """
    Ensure job hunting tables exist in Lakebase.
    Job postings and embeddings tables should exist from setup scripts.
    """
    # Create saved_jobs table if it doesn't exist
    lakebase.run_write(
        f"""
        CREATE TABLE IF NOT EXISTS {SAVED_JOBS_TABLE_NAME} (
            saved_job_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL DEFAULT 1,
            job_id INTEGER NOT NULL REFERENCES {JOBS_TABLE_NAME}(job_id),
            notes TEXT,
            saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, job_id)
        )
        """
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{SAVED_JOBS_TABLE_NAME}_user "
        f"ON {SAVED_JOBS_TABLE_NAME} (user_id)"
    )


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.errorhandler(Exception)
def handle_exception(err):
    """Ensure all unhandled errors return JSON (not an HTML error page)."""
    logger.exception("Unhandled exception while processing request")
    status_code = getattr(err, "code", 500)
    if not isinstance(status_code, int):
        status_code = 500
    return jsonify({"error": str(err)}), status_code


@app.route("/")
def index():
    """Simple UI for the job hunting app."""
    return render_template("index.html")


@app.route("/jobs")
def list_jobs():
    """List all job postings with optional filters."""
    limit = int(request.args.get("limit", 20))
    location = request.args.get("location")
    min_salary = request.args.get("min_salary")
    
    where_clauses = []
    params = []
    
    if location:
        where_clauses.append("location ILIKE %s")
        params.append(f"%{location}%")
    
    if min_salary:
        where_clauses.append("(salary_min >= %s OR salary_max >= %s)")
        params.extend([float(min_salary), float(min_salary)])
    
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.append(limit)
    
    rows = lakebase.run_query(
        f"""
        SELECT job_id, title, company, location, 
               salary_min, salary_max, description, 
               category, created_date, url
        FROM {JOBS_TABLE_NAME} 
        {where_sql}
        ORDER BY created_date DESC 
        LIMIT %s
        """,
        tuple(params),
    )
    return jsonify({"jobs": rows, "count": len(rows)})


@app.route("/jobs/<int:job_id>")
def get_job(job_id):
    """Get details for a specific job."""
    rows = lakebase.run_query(
        f"""
        SELECT job_id, title, company, location, 
               salary_min, salary_max, description, 
               category, created_date, url
        FROM {JOBS_TABLE_NAME}
        WHERE job_id = %s
        """,
        (job_id,)
    )
    
    if not rows:
        return jsonify({"error": "Job not found"}), 404
    
    return jsonify(rows[0])


@app.route("/jobs/search", methods=["POST"])
def search_jobs():
    """
    Semantic search over job postings using vector embeddings (NO LLM!).
    
    Body (JSON): {
        "query": "Python backend developer", 
        "location": "London",
        "min_salary": 70000,
        "top_k": 10
    }
    
    - query: Natural language search query (required)
    - location: Location filter (optional)
    - min_salary: Minimum salary filter (optional)
    - top_k: Number of results to return (default: 10, max: 50)
    
    Returns: List of matching jobs with similarity scores
    """
    body = request.json if request.is_json else {}
    query = body.get("query", "").strip()
    location = body.get("location", "").strip() if body.get("location") else None
    min_salary = body.get("min_salary")
    top_k = body.get("top_k", 10)
    
    # Validate query
    if not query:
        return jsonify({"error": "Query string is required"}), 400
    
    # Clamp top_k to reasonable bounds
    try:
        top_k = int(top_k)
        top_k = max(1, min(50, top_k))
    except (ValueError, TypeError):
        return jsonify({"error": "top_k must be an integer"}), 400
    
    # Check if embeddings table exists and has data
    try:
        count_result = lakebase.run_query(
            f"SELECT COUNT(*) as count FROM {EMBEDDINGS_TABLE_NAME}",
            ()
        )
        if not count_result or count_result[0].get("count", 0) == 0:
            return jsonify({
                "error": "No job embeddings found. Please run the embeddings generation script first.",
                "results": []
            }), 404
    except Exception as e:
        logger.error(f"Error checking embeddings table: {e}")
        return jsonify({
            "error": "Embeddings table not found. Please run the embeddings generation script first.",
            "results": []
        }), 404
    
    # Embed the query
    try:
        logger.info(f"Embedding query: {query}")
        query_embedding = _embedding_model.encode([query])[0].tolist()
    except Exception as e:
        logger.error(f"Error embedding query: {e}")
        return jsonify({"error": f"Failed to embed query: {str(e)}"}), 500
    
    # Build SQL with filters
    where_clauses = []
    params = [query_embedding]
    
    if location:
        where_clauses.append("j.location ILIKE %s")
        params.append(f"%{location}%")
    
    if min_salary:
        try:
            min_sal = float(min_salary)
            where_clauses.append("(j.salary_min >= %s OR j.salary_max >= %s)")
            params.extend([min_sal, min_sal])
        except (ValueError, TypeError):
            pass
    
    where_sql = f"AND {' AND '.join(where_clauses)}" if where_clauses else ""
    
    # Add embedding for ORDER BY and LIMIT
    params.extend([query_embedding, top_k])
    
    # Run cosine similarity search using pgvector
    try:
        embedding_str = '{' + ','.join(str(float(x)) for x in query_embedding) + '}'
        
        results = lakebase.run_query(
            f"""
            SELECT 
                j.job_id,
                j.title,
                j.company,
                j.location,
                j.salary_min,
                j.salary_max,
                j.description,
                j.category,
                j.created_date,
                j.url,
                1 - (e.embedding <=> %s::vector) AS similarity
            FROM {EMBEDDINGS_TABLE_NAME} e
            JOIN {JOBS_TABLE_NAME} j ON j.job_id = e.job_id
            WHERE 1=1 {where_sql}
            ORDER BY e.embedding <=> %s::vector
            LIMIT %s
            """,
            tuple(params)
        )
        
        logger.info(f"Found {len(results)} results for query: {query}")
        return jsonify({
            "query": query,
            "location": location,
            "min_salary": min_salary,
            "top_k": top_k,
            "results": results,
            "count": len(results)
        })
        
    except Exception as e:
        logger.error(f"Error during semantic search: {e}", exc_info=True)
        return jsonify({"error": f"Search failed: {str(e)}"}), 500


@app.route("/jobs/save", methods=["POST"])
def save_job():
    """
    Save a job to user's favorites.
    
    Body (JSON): {"job_id": 123, "user_id": 1, "notes": "Interesting position"}
    
    Returns: {"saved_job_id": <id>, "message": "Job saved"}
    """
    ensure_tables()
    
    body = request.json if request.is_json else {}
    job_id = body.get("job_id")
    user_id = body.get("user_id", 1)
    notes = body.get("notes", "")
    
    if not job_id:
        return jsonify({"error": "job_id is required"}), 400
    
    try:
        with lakebase.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {SAVED_JOBS_TABLE_NAME} (user_id, job_id, notes)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, job_id) 
                    DO UPDATE SET notes = EXCLUDED.notes, saved_at = now()
                    RETURNING saved_job_id
                    """,
                    (user_id, job_id, notes)
                )
                saved_job_id = cur.fetchone()[0]
                conn.commit()
        
        return jsonify({
            "saved_job_id": saved_job_id,
            "message": f"Job {job_id} saved to favorites"
        })
    
    except Exception as e:
        logger.error(f"Error saving job: {e}", exc_info=True)
        return jsonify({"error": f"Failed to save job: {str(e)}"}), 500


@app.route("/jobs/saved")
def list_saved_jobs():
    """
    List saved jobs for a user.
    
    Query params: user_id (default: 1)
    
    Returns: List of saved jobs with full job details
    """
    user_id = request.args.get("user_id", 1)
    
    try:
        rows = lakebase.run_query(
            f"""
            SELECT 
                s.saved_job_id,
                s.user_id,
                s.notes,
                s.saved_at,
                j.job_id,
                j.title,
                j.company,
                j.location,
                j.salary_min,
                j.salary_max,
                j.description,
                j.category,
                j.url
            FROM {SAVED_JOBS_TABLE_NAME} s
            JOIN {JOBS_TABLE_NAME} j ON j.job_id = s.job_id
            WHERE s.user_id = %s
            ORDER BY s.saved_at DESC
            """,
            (user_id,)
        )
        
        return jsonify({"saved_jobs": rows, "count": len(rows)})
    
    except Exception as e:
        logger.error(f"Error fetching saved jobs: {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch saved jobs: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
