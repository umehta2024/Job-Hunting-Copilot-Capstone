"""
Databricks Job Hunting Copilot App:
- Serves a Flask API for job search
- Reads/writes to Lakebase (Databricks-managed Postgres) via lakebase.py
- Provides semantic job search using vector embeddings (NO LLM needed!)
- Tracks user profile, application pipeline, interviews, and networking contacts

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
PROFILES_TABLE_NAME = os.environ.get("PROFILES_TABLE_NAME", "profiles")
SKILLS_TABLE_NAME = os.environ.get("SKILLS_TABLE_NAME", "skills")
APPLICATIONS_TABLE_NAME = os.environ.get("APPLICATIONS_TABLE_NAME", "applications")
INTERVIEW_NOTES_TABLE_NAME = os.environ.get("INTERVIEW_NOTES_TABLE_NAME", "interview_notes")
CONTACTS_TABLE_NAME = os.environ.get("CONTACTS_TABLE_NAME", "contacts")
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Statuses considered "active" for staleness checks (terminal statuses are excluded)
ACTIVE_APPLICATION_STATUSES = ("applied", "interviewing", "offered")
VALID_APPLICATION_STATUSES = (
    "applied",
    "interviewing",
    "offered",
    "rejected",
    "accepted",
    "withdrawn",
)
VALID_INTERVIEW_TYPES = ("phone", "video", "onsite", "technical", "behavioral")

# Load embedding model once at module level for semantic search
logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}...")
_embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
logger.info("Embedding model loaded")


def ensure_tables():
    """
    Ensure job hunting tables exist in Lakebase.
    job_postings / job_embeddings should exist from setup scripts.
    Everything else (including a minimal `users` row for the default
    single-user flow) is created here so the app works on a fresh DB.
    """
    # Minimal users table -- this app operates single-tenant (user_id=1)
    # by default, but keeps the FK relationships from the full schema.
    lakebase.run_write(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL DEFAULT '',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Ensure a default user row exists for user_id=1
    lakebase.run_write(
        """
        INSERT INTO users (user_id, email, password_hash)
        VALUES (1, 'default@local', '')
        ON CONFLICT (user_id) DO NOTHING
        """
    )

    lakebase.run_write(
        f"""
        CREATE TABLE IF NOT EXISTS {PROFILES_TABLE_NAME} (
            profile_id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            full_name VARCHAR(255),
            phone VARCHAR(20),
            location VARCHAR(255),
            linkedin_url VARCHAR(500),
            github_url VARCHAR(500),
            portfolio_url VARCHAR(500),
            bio TEXT,
            preferences JSONB DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{PROFILES_TABLE_NAME}_user_id "
        f"ON {PROFILES_TABLE_NAME} (user_id)"
    )

    lakebase.run_write(
        f"""
        CREATE TABLE IF NOT EXISTS {SKILLS_TABLE_NAME} (
            skill_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            skill_name VARCHAR(100) NOT NULL,
            proficiency_level VARCHAR(20) CHECK (
                proficiency_level IN ('beginner', 'intermediate', 'advanced', 'expert')
            ),
            years_of_experience DECIMAL(3,1),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, skill_name)
        )
        """
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{SKILLS_TABLE_NAME}_user_id "
        f"ON {SKILLS_TABLE_NAME} (user_id)"
    )

    lakebase.run_write(
        f"""
        CREATE TABLE IF NOT EXISTS {APPLICATIONS_TABLE_NAME} (
            application_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            job_id INTEGER NOT NULL REFERENCES {JOBS_TABLE_NAME}(job_id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'applied' CHECK (
                status IN ('applied', 'interviewing', 'offered', 'rejected', 'accepted', 'withdrawn')
            ),
            applied_date DATE DEFAULT CURRENT_DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, job_id)
        )
        """
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{APPLICATIONS_TABLE_NAME}_user_id "
        f"ON {APPLICATIONS_TABLE_NAME} (user_id)"
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{APPLICATIONS_TABLE_NAME}_status "
        f"ON {APPLICATIONS_TABLE_NAME} (status)"
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{APPLICATIONS_TABLE_NAME}_applied_date "
        f"ON {APPLICATIONS_TABLE_NAME} (applied_date)"
    )

    lakebase.run_write(
        f"""
        CREATE TABLE IF NOT EXISTS {INTERVIEW_NOTES_TABLE_NAME} (
            note_id SERIAL PRIMARY KEY,
            application_id INTEGER NOT NULL REFERENCES {APPLICATIONS_TABLE_NAME}(application_id) ON DELETE CASCADE,
            interview_date DATE,
            interview_type VARCHAR(20) CHECK (
                interview_type IN ('phone', 'video', 'onsite', 'technical', 'behavioral')
            ),
            interviewer_name VARCHAR(255),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{INTERVIEW_NOTES_TABLE_NAME}_application_id "
        f"ON {INTERVIEW_NOTES_TABLE_NAME} (application_id)"
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{INTERVIEW_NOTES_TABLE_NAME}_date "
        f"ON {INTERVIEW_NOTES_TABLE_NAME} (interview_date)"
    )

    lakebase.run_write(
        f"""
        CREATE TABLE IF NOT EXISTS {CONTACTS_TABLE_NAME} (
            contact_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            company VARCHAR(255),
            title VARCHAR(255),
            email VARCHAR(255),
            phone VARCHAR(20),
            linkedin_url VARCHAR(500),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{CONTACTS_TABLE_NAME}_user_id "
        f"ON {CONTACTS_TABLE_NAME} (user_id)"
    )
    lakebase.run_write(
        f"CREATE INDEX IF NOT EXISTS idx_{CONTACTS_TABLE_NAME}_company "
        f"ON {CONTACTS_TABLE_NAME} (company)"
    )

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


# ============================================================
# PROFILE
# ============================================================

@app.route("/profile", methods=["POST"])
def upsert_profile():
    """
    Create or update the current user's profile (upsert on user_id).

    Body (JSON): {
        "user_id": 1,                       # optional, default 1
        "full_name": "Jane Doe",
        "phone": "555-123-4567",
        "location": "London, UK",
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "github_url": "https://github.com/janedoe",
        "portfolio_url": "https://janedoe.dev",
        "bio": "Backend engineer with 5 years of Python experience...",
        "preferences": {"min_salary": 90000, "remote_only": true},
        "skills": [
            {"skill_name": "Python", "proficiency_level": "expert", "years_of_experience": 5},
            {"skill_name": "SQL", "proficiency_level": "advanced"}
        ]
    }

    `skills`, if provided, fully replaces the user's existing skill rows.

    Returns: The saved profile (with skills).
    """
    ensure_tables()

    body = request.json if request.is_json else {}
    user_id = body.get("user_id", 1)

    full_name = body.get("full_name")
    phone = body.get("phone")
    location = body.get("location")
    linkedin_url = body.get("linkedin_url")
    github_url = body.get("github_url")
    portfolio_url = body.get("portfolio_url")
    bio = body.get("bio")
    preferences = body.get("preferences", {})
    skills = body.get("skills")

    if skills is not None and not isinstance(skills, list):
        return jsonify({"error": "skills must be a list of objects"}), 400

    try:
        preferences_json = _json.dumps(preferences)
    except (TypeError, ValueError):
        return jsonify({"error": "preferences must be JSON-serializable"}), 400

    try:
        with lakebase.get_connection() as conn:
            with conn.cursor() as cur:
                # Make sure the referenced user row exists (single-tenant default)
                cur.execute(
                    """
                    INSERT INTO users (user_id, email, password_hash)
                    VALUES (%s, %s, '')
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (user_id, body.get("email", f"user{user_id}@local")),
                )

                cur.execute(
                    f"""
                    INSERT INTO {PROFILES_TABLE_NAME}
                        (user_id, full_name, phone, location, linkedin_url,
                         github_url, portfolio_url, bio, preferences)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (user_id) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        phone = EXCLUDED.phone,
                        location = EXCLUDED.location,
                        linkedin_url = EXCLUDED.linkedin_url,
                        github_url = EXCLUDED.github_url,
                        portfolio_url = EXCLUDED.portfolio_url,
                        bio = EXCLUDED.bio,
                        preferences = EXCLUDED.preferences,
                        updated_at = now()
                    RETURNING profile_id
                    """,
                    (
                        user_id, full_name, phone, location, linkedin_url,
                        github_url, portfolio_url, bio, preferences_json,
                    ),
                )
                profile_id = cur.fetchone()[0]

                if skills is not None:
                    cur.execute(
                        f"DELETE FROM {SKILLS_TABLE_NAME} WHERE user_id = %s",
                        (user_id,),
                    )
                    for skill in skills:
                        skill_name = (skill or {}).get("skill_name")
                        if not skill_name:
                            continue
                        proficiency_level = skill.get("proficiency_level")
                        years_of_experience = skill.get("years_of_experience")
                        cur.execute(
                            f"""
                            INSERT INTO {SKILLS_TABLE_NAME}
                                (user_id, skill_name, proficiency_level, years_of_experience)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (user_id, skill_name) DO UPDATE SET
                                proficiency_level = EXCLUDED.proficiency_level,
                                years_of_experience = EXCLUDED.years_of_experience
                            """,
                            (user_id, skill_name, proficiency_level, years_of_experience),
                        )

                conn.commit()

        profile_rows = lakebase.run_query(
            f"SELECT * FROM {PROFILES_TABLE_NAME} WHERE profile_id = %s",
            (profile_id,),
        )
        skill_rows = lakebase.run_query(
            f"SELECT skill_name, proficiency_level, years_of_experience "
            f"FROM {SKILLS_TABLE_NAME} WHERE user_id = %s ORDER BY skill_name",
            (user_id,),
        )

        profile = profile_rows[0] if profile_rows else {}
        profile["skills"] = skill_rows
        return jsonify(profile)

    except Exception as e:
        logger.error(f"Error saving profile: {e}", exc_info=True)
        return jsonify({"error": f"Failed to save profile: {str(e)}"}), 500


@app.route("/profile")
def get_profile():
    """Get the current user's profile (with skills). Query params: user_id (default 1)."""
    user_id = request.args.get("user_id", 1)

    try:
        profile_rows = lakebase.run_query(
            f"SELECT * FROM {PROFILES_TABLE_NAME} WHERE user_id = %s",
            (user_id,),
        )
        if not profile_rows:
            return jsonify({"error": "Profile not found"}), 404

        skill_rows = lakebase.run_query(
            f"SELECT skill_name, proficiency_level, years_of_experience "
            f"FROM {SKILLS_TABLE_NAME} WHERE user_id = %s ORDER BY skill_name",
            (user_id,),
        )

        profile = profile_rows[0]
        profile["skills"] = skill_rows
        return jsonify(profile)

    except Exception as e:
        logger.error(f"Error fetching profile: {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch profile: {str(e)}"}), 500


# ============================================================
# APPLICATIONS
# ============================================================

@app.route("/applications", methods=["POST"])
def upsert_application():
    """
    Create or update an application's status for a (user_id, job_id) pair.

    Body (JSON): {
        "job_id": 123,
        "user_id": 1,                 # optional, default 1
        "status": "interviewing",     # applied|interviewing|offered|rejected|accepted|withdrawn
        "applied_date": "2026-07-01", # optional, defaults to today on first insert
        "notes": "Recruiter screen scheduled for next week"
    }

    Upserts on (user_id, job_id): re-posting for a job you've already
    applied to updates its status/notes instead of creating a duplicate.

    Returns: The saved application row.
    """
    ensure_tables()

    body = request.json if request.is_json else {}
    job_id = body.get("job_id")
    user_id = body.get("user_id", 1)
    status = body.get("status", "applied")
    applied_date = body.get("applied_date")
    notes = body.get("notes")

    if not job_id:
        return jsonify({"error": "job_id is required"}), 400

    if status not in VALID_APPLICATION_STATUSES:
        return jsonify({
            "error": f"status must be one of {VALID_APPLICATION_STATUSES}"
        }), 400

    job_rows = lakebase.run_query(
        f"SELECT job_id FROM {JOBS_TABLE_NAME} WHERE job_id = %s",
        (job_id,),
    )
    if not job_rows:
        return jsonify({"error": f"Job {job_id} not found"}), 404

    try:
        with lakebase.get_connection() as conn:
            with conn.cursor() as cur:
                if applied_date:
                    cur.execute(
                        f"""
                        INSERT INTO {APPLICATIONS_TABLE_NAME}
                            (user_id, job_id, status, applied_date, notes)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, job_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            applied_date = EXCLUDED.applied_date,
                            notes = COALESCE(EXCLUDED.notes, {APPLICATIONS_TABLE_NAME}.notes),
                            updated_at = now()
                        RETURNING application_id
                        """,
                        (user_id, job_id, status, applied_date, notes),
                    )
                else:
                    cur.execute(
                        f"""
                        INSERT INTO {APPLICATIONS_TABLE_NAME}
                            (user_id, job_id, status, notes)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id, job_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            notes = COALESCE(EXCLUDED.notes, {APPLICATIONS_TABLE_NAME}.notes),
                            updated_at = now()
                        RETURNING application_id
                        """,
                        (user_id, job_id, status, notes),
                    )
                application_id = cur.fetchone()[0]
                conn.commit()

        rows = lakebase.run_query(
            f"SELECT * FROM {APPLICATIONS_TABLE_NAME} WHERE application_id = %s",
            (application_id,),
        )
        return jsonify(rows[0])

    except Exception as e:
        logger.error(f"Error saving application: {e}", exc_info=True)
        return jsonify({"error": f"Failed to save application: {str(e)}"}), 500


@app.route("/applications")
def list_applications():
    """
    List applications for a user, optionally filtered by status.

    Query params: user_id (default 1), status (optional)
    """
    user_id = request.args.get("user_id", 1)
    status = request.args.get("status")

    where_clauses = ["a.user_id = %s"]
    params = [user_id]

    if status:
        if status not in VALID_APPLICATION_STATUSES:
            return jsonify({
                "error": f"status must be one of {VALID_APPLICATION_STATUSES}"
            }), 400
        where_clauses.append("a.status = %s")
        params.append(status)

    where_sql = " AND ".join(where_clauses)

    try:
        rows = lakebase.run_query(
            f"""
            SELECT
                a.application_id, a.user_id, a.job_id, a.status,
                a.applied_date, a.notes, a.created_at, a.updated_at,
                j.title, j.company, j.location, j.url
            FROM {APPLICATIONS_TABLE_NAME} a
            JOIN {JOBS_TABLE_NAME} j ON j.job_id = a.job_id
            WHERE {where_sql}
            ORDER BY a.applied_date DESC
            """,
            tuple(params),
        )
        return jsonify({"applications": rows, "count": len(rows)})

    except Exception as e:
        logger.error(f"Error fetching applications: {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch applications: {str(e)}"}), 500


@app.route("/applications/stale")
def stale_applications():
    """
    Find applications that have been sitting in an active status
    (applied/interviewing/offered) without an update for a while --
    good candidates for a follow-up nudge.

    Query params:
        user_id (default 1)
        days (default 14) -- days since last update to count as "stale"

    Returns: Stale applications, oldest-updated first.
    """
    user_id = request.args.get("user_id", 1)

    try:
        days = int(request.args.get("days", 14))
        if days < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "days must be a non-negative integer"}), 400

    try:
        rows = lakebase.run_query(
            f"""
            SELECT
                a.application_id, a.user_id, a.job_id, a.status,
                a.applied_date, a.notes, a.created_at, a.updated_at,
                j.title, j.company, j.location, j.url,
                (CURRENT_DATE - a.updated_at::date) AS days_since_update
            FROM {APPLICATIONS_TABLE_NAME} a
            JOIN {JOBS_TABLE_NAME} j ON j.job_id = a.job_id
            WHERE a.user_id = %s
              AND a.status = ANY(%s)
              AND a.updated_at < now() - (%s || ' days')::interval
            ORDER BY a.updated_at ASC
            """,
            (user_id, list(ACTIVE_APPLICATION_STATUSES), days),
        )
        return jsonify({"stale_applications": rows, "count": len(rows), "days_threshold": days})

    except Exception as e:
        logger.error(f"Error fetching stale applications: {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch stale applications: {str(e)}"}), 500


# ============================================================
# INTERVIEWS
# ============================================================

@app.route("/interviews", methods=["POST"])
def log_interview():
    """
    Log an interview note against an existing application.

    Body (JSON): {
        "application_id": 5,
        "interview_date": "2026-08-12",
        "interview_type": "technical",   # phone|video|onsite|technical|behavioral
        "interviewer_name": "Alex Kim",
        "notes": "Focused on system design; asked about queueing."
    }

    Also bumps the parent application's status to "interviewing" if it
    isn't already past that stage (offered/rejected/accepted/withdrawn
    are left untouched).

    Returns: The saved interview note.
    """
    ensure_tables()

    body = request.json if request.is_json else {}
    application_id = body.get("application_id")
    interview_date = body.get("interview_date")
    interview_type = body.get("interview_type")
    interviewer_name = body.get("interviewer_name")
    notes = body.get("notes")

    if not application_id:
        return jsonify({"error": "application_id is required"}), 400

    if interview_type and interview_type not in VALID_INTERVIEW_TYPES:
        return jsonify({
            "error": f"interview_type must be one of {VALID_INTERVIEW_TYPES}"
        }), 400

    app_rows = lakebase.run_query(
        f"SELECT application_id, status FROM {APPLICATIONS_TABLE_NAME} WHERE application_id = %s",
        (application_id,),
    )
    if not app_rows:
        return jsonify({"error": "Application not found"}), 404

    try:
        with lakebase.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {INTERVIEW_NOTES_TABLE_NAME}
                        (application_id, interview_date, interview_type, interviewer_name, notes)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING note_id
                    """,
                    (application_id, interview_date, interview_type, interviewer_name, notes),
                )
                note_id = cur.fetchone()[0]

                if app_rows[0]["status"] == "applied":
                    cur.execute(
                        f"""
                        UPDATE {APPLICATIONS_TABLE_NAME}
                        SET status = 'interviewing', updated_at = now()
                        WHERE application_id = %s
                        """,
                        (application_id,),
                    )

                conn.commit()

        rows = lakebase.run_query(
            f"SELECT * FROM {INTERVIEW_NOTES_TABLE_NAME} WHERE note_id = %s",
            (note_id,),
        )
        return jsonify(rows[0])

    except Exception as e:
        logger.error(f"Error logging interview: {e}", exc_info=True)
        return jsonify({"error": f"Failed to log interview: {str(e)}"}), 500


@app.route("/interviews")
def list_interviews():
    """
    List interview notes, optionally filtered by application.

    Query params: application_id (optional), user_id (default 1, used
    only when application_id is omitted, to scope by owner)
    """
    application_id = request.args.get("application_id")
    user_id = request.args.get("user_id", 1)

    if application_id:
        where_sql = "i.application_id = %s"
        params = (application_id,)
    else:
        where_sql = "a.user_id = %s"
        params = (user_id,)

    try:
        rows = lakebase.run_query(
            f"""
            SELECT
                i.note_id, i.application_id, i.interview_date, i.interview_type,
                i.interviewer_name, i.notes, i.created_at,
                a.job_id, j.title, j.company
            FROM {INTERVIEW_NOTES_TABLE_NAME} i
            JOIN {APPLICATIONS_TABLE_NAME} a ON a.application_id = i.application_id
            JOIN {JOBS_TABLE_NAME} j ON j.job_id = a.job_id
            WHERE {where_sql}
            ORDER BY i.interview_date DESC NULLS LAST, i.created_at DESC
            """,
            params,
        )
        return jsonify({"interviews": rows, "count": len(rows)})

    except Exception as e:
        logger.error(f"Error fetching interviews: {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch interviews: {str(e)}"}), 500


# ============================================================
# CONTACTS (networking)
# ============================================================

@app.route("/contacts", methods=["GET"])
def list_contacts():
    """
    List networking contacts for a user, with optional search.

    Query params:
        user_id (default 1)
        q (optional) -- matches against name or company
        company (optional) -- exact-ish company filter
    """
    ensure_tables()

    user_id = request.args.get("user_id", 1)
    q = request.args.get("q")
    company = request.args.get("company")

    where_clauses = ["user_id = %s"]
    params = [user_id]

    if q:
        where_clauses.append("(name ILIKE %s OR company ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])

    if company:
        where_clauses.append("company ILIKE %s")
        params.append(f"%{company}%")

    where_sql = " AND ".join(where_clauses)

    try:
        rows = lakebase.run_query(
            f"""
            SELECT contact_id, user_id, name, company, title, email,
                   phone, linkedin_url, notes, created_at, updated_at
            FROM {CONTACTS_TABLE_NAME}
            WHERE {where_sql}
            ORDER BY updated_at DESC
            """,
            tuple(params),
        )
        return jsonify({"contacts": rows, "count": len(rows)})

    except Exception as e:
        logger.error(f"Error fetching contacts: {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch contacts: {str(e)}"}), 500


@app.route("/contacts", methods=["POST"])
def create_contact():
    """
    Add a networking contact. Not explicitly requested, but included so
    /contacts is actually usable end-to-end (GET alone has nothing to list).

    Body (JSON): {
        "user_id": 1,
        "name": "Alex Kim",
        "company": "Acme Corp",
        "title": "Engineering Manager",
        "email": "alex@acme.com",
        "phone": "555-000-1111",
        "linkedin_url": "https://linkedin.com/in/alexkim",
        "notes": "Met at PyCon; offered to refer me internally."
    }
    """
    ensure_tables()

    body = request.json if request.is_json else {}
    user_id = body.get("user_id", 1)
    name = body.get("name")

    if not name:
        return jsonify({"error": "name is required"}), 400

    try:
        with lakebase.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (user_id, email, password_hash)
                    VALUES (%s, %s, '')
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (user_id, f"user{user_id}@local"),
                )
                cur.execute(
                    f"""
                    INSERT INTO {CONTACTS_TABLE_NAME}
                        (user_id, name, company, title, email, phone, linkedin_url, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING contact_id
                    """,
                    (
                        user_id, name, body.get("company"), body.get("title"),
                        body.get("email"), body.get("phone"),
                        body.get("linkedin_url"), body.get("notes"),
                    ),
                )
                contact_id = cur.fetchone()[0]
                conn.commit()

        rows = lakebase.run_query(
            f"SELECT * FROM {CONTACTS_TABLE_NAME} WHERE contact_id = %s",
            (contact_id,),
        )
        return jsonify(rows[0])

    except Exception as e:
        logger.error(f"Error creating contact: {e}", exc_info=True)
        return jsonify({"error": f"Failed to create contact: {str(e)}"}), 500


if __name__ == "__main__":
    ensure_tables()
    port = int(os.environ.get("DATABRICKS_APP_PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)