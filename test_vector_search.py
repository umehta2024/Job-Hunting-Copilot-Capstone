# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Job Hunting Vector Search - NO LLM Required!
# MAGIC %md
# MAGIC # 🔍 Job Hunting with Vector Search
# MAGIC ## 100% Free - No API Costs, No LLMs!
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## ✅ What You Have:
# MAGIC
# MAGIC 📊 **100 jobs in Lakebase Postgres**  
# MAGIC 🧠 **384-dim embeddings** (sentence-transformers)  
# MAGIC ⚡ **pgvector** for fast similarity search  
# MAGIC 🎯 **Semantic search** - understands meaning, not just keywords  
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## ℹ️ How It Works:
# MAGIC
# MAGIC 1. Your query: `"Python backend developer"`
# MAGIC 2. Converts to 384-number vector
# MAGIC 3. Compares to all job vectors in database
# MAGIC 4. Returns top matches sorted by similarity
# MAGIC
# MAGIC **No LLM needed!** This is pure math + database queries.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 🚀 Let's Test It!

# COMMAND ----------

# DBTITLE 1,Step 1: Install sentence-transformers
# MAGIC %pip install -q sentence-transformers

# COMMAND ----------

# DBTITLE 1,Option A: Direct Vector Search (NO LLM!)
# Direct vector search - NO LLM, NO API costs!
# Pure Python + pgvector

import sys
sys.path.append('/Workspace/Users/upasana.mehta04@gmail.com/Job-Hunting-Copilot-Capstone')

import psycopg2
from psycopg2.extras import RealDictCursor
from sentence_transformers import SentenceTransformer
import base64
from databricks.sdk.runtime import dbutils

def get_secret(scope, key):
    secret_bytes = dbutils.secrets.get(scope=scope, key=key)
    try:
        return base64.b64decode(secret_bytes).decode("utf-8")
    except:
        return secret_bytes

# Connect to database
conn = psycopg2.connect(get_secret("job_hunting", "lakebase_url"))

# Load embedding model (one time)
print("Loading embedding model...")
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
print("✅ Model loaded!\n")

# Direct vector search - NO LLM!
def search_jobs_direct(query, location=None, min_salary=None, top_k=10):
    """Direct vector search without any LLM."""
    
    # Generate query embedding
    query_embedding = model.encode(query).tolist()
    
    # SQL query
    sql = """
        SELECT 
            jp.job_id,
            jp.title,
            jp.company,
            jp.location,
            jp.salary_min,
            jp.salary_max,
            1 - (je.embedding <=> %s::vector) AS similarity
        FROM job_embeddings je
        JOIN job_postings jp ON je.job_id = jp.job_id
        WHERE 1=1
    """
    
    params = [query_embedding]
    
    if location:
        sql += " AND jp.location ILIKE %s"
        params.append(f"%{location}%")
    
    if min_salary:
        sql += " AND (jp.salary_min >= %s OR jp.salary_max >= %s)"
        params.extend([min_salary, min_salary])
    
    sql += " ORDER BY je.embedding <=> %s::vector LIMIT %s;"
    params.extend([query_embedding, top_k])
    
    # Execute
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()

# TEST IT!
print("🔍 Searching for 'Python backend developer in London'...\n")
results = search_jobs_direct(
    query="Python backend developer",
    location="London",
    min_salary=70000,
    top_k=5
)

print(f"Found {len(results)} jobs:\n")
for i, job in enumerate(results, 1):
    print(f"{i}. {job['title']} at {job['company']}")
    print(f"   Location: {job['location']}")
    if job['salary_min']:
        print(f"   Salary: £{job['salary_min']:,} - £{job['salary_max']:,}")
    print(f"   Similarity: {job['similarity']:.3f}")
    print()

print("\n" + "="*70)
print("✅ NO LLM NEEDED! This is pure Python + pgvector!")
print("="*70)

# COMMAND ----------

# DBTITLE 1,When You WOULD Need Gemini
# MAGIC %md
# MAGIC ## 🎯 What You Have Here
# MAGIC
# MAGIC **100% Free Job Search with AI Vector Embeddings**
# MAGIC
# MAGIC ✅ **NO API costs** - No OpenAI, no Gemini, no LLM charges  
# MAGIC ✅ **Semantic search** - Finds jobs by meaning, not just keywords  
# MAGIC ✅ **Pure Python** - Direct database queries with pgvector  
# MAGIC ✅ **Full control** - You control everything  
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 🏗️ Architecture
# MAGIC
# MAGIC ```
# MAGIC ┌─────────────────────────┐
# MAGIC │ Your Search Query       │
# MAGIC │ "Python developer"      │
# MAGIC └───────────┬─────────────┘
# MAGIC             │
# MAGIC             ▼
# MAGIC ┌─────────────────────────┐
# MAGIC │ sentence-transformers   │
# MAGIC │ Converts to vector      │
# MAGIC │ [0.123, -0.45, ...]     │
# MAGIC └───────────┬─────────────┘
# MAGIC             │
# MAGIC             ▼
# MAGIC ┌─────────────────────────┐
# MAGIC │ Lakebase Postgres       │
# MAGIC │ pgvector similarity     │
# MAGIC │ (cosine distance)       │
# MAGIC └───────────┬─────────────┘
# MAGIC             │
# MAGIC             ▼
# MAGIC ┌─────────────────────────┐
# MAGIC │ Ranked Job Results      │
# MAGIC │ 1. Python Dev - 0.92    │
# MAGIC │ 2. Backend Eng - 0.88   │
# MAGIC └─────────────────────────┘
# MAGIC ```
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 💡 What You Can Build
# MAGIC
# MAGIC ### Option 1: Streamlit Web UI
# MAGIC * Search bar + filters
# MAGIC * Display job cards
# MAGIC * Click to save favorites
# MAGIC * **Example:** Traditional job board interface
# MAGIC
# MAGIC ### Option 2: Flask REST API
# MAGIC * `/api/search?query=...`
# MAGIC * `/api/job/{id}`
# MAGIC * `/api/save_job`
# MAGIC * **Example:** Backend for mobile app or website
# MAGIC
# MAGIC ### Option 3: Python Scripts
# MAGIC * Automated job monitoring
# MAGIC * Daily email alerts for new matches
# MAGIC * Bulk data analysis
# MAGIC * **Example:** "Email me new Python jobs every morning"
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ## 🚀 Next Steps
# MAGIC
# MAGIC 1. ✅ Run the cell below to test vector search
# MAGIC 2. Build a simple Streamlit UI
# MAGIC 3. Add more jobs to your database
# MAGIC 4. Deploy your job search app!