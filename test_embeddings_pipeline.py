# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Test Embeddings Pipeline
# MAGIC %md
# MAGIC # Test Embeddings Generation Pipeline
# MAGIC
# MAGIC This notebook will:
# MAGIC 1. ✅ Verify job_embeddings table exists in Lakebase
# MAGIC 2. ✅ Check table structure and indexes
# MAGIC 3. ✅ Run embedding generation for all 100 jobs
# MAGIC 4. ✅ Verify embeddings were created
# MAGIC 5. ✅ Test a sample semantic search query

# COMMAND ----------

# DBTITLE 1,Step 1: Verify job_embeddings Table
# Step 1: Check if job_embeddings table exists and inspect structure
import psycopg2
import base64
from databricks.sdk.runtime import dbutils

def get_secret(scope, key):
    secret_bytes = dbutils.secrets.get(scope=scope, key=key)
    try:
        return base64.b64decode(secret_bytes).decode("utf-8")
    except:
        return secret_bytes

print("Checking job_embeddings table in Lakebase...\n")

try:
    lakebase_url = get_secret("job_hunting", "lakebase_url")
    conn = psycopg2.connect(lakebase_url)
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'job_embeddings'
        );
    """)
    table_exists = cursor.fetchone()[0]
    
    if not table_exists:
        print("❌ job_embeddings table does NOT exist")
        print("   Run sql/setup_job_embeddings_384.sql first!")
    else:
        print("✅ job_embeddings table exists\n")
        
        # Get table structure
        cursor.execute("""
            SELECT 
                column_name,
                data_type,
                udt_name,
                is_nullable
            FROM information_schema.columns
            WHERE table_name = 'job_embeddings'
            ORDER BY ordinal_position;
        """)
        
        print("📋 Table Structure:")
        print("-" * 60)
        for row in cursor.fetchall():
            col_name, data_type, udt_name, nullable = row
            print(f"  {col_name:20s} {udt_name:15s} {'NULL' if nullable == 'YES' else 'NOT NULL'}")
        
        # Check indexes
        cursor.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'job_embeddings';
        """)
        
        indexes = cursor.fetchall()
        print(f"\n🔍 Indexes: {len(indexes)} found")
        for idx_name, idx_def in indexes:
            print(f"  - {idx_name}")
        
        # Check current row count
        cursor.execute("SELECT COUNT(*) FROM job_embeddings;")
        count = cursor.fetchone()[0]
        print(f"\n📊 Current embeddings count: {count}")
        
        # Check how many jobs need embeddings
        cursor.execute("""
            SELECT COUNT(*)
            FROM job_postings jp
            LEFT JOIN job_embeddings je ON jp.job_id = je.job_id
            WHERE je.job_id IS NULL
            AND jp.description IS NOT NULL;
        """)
        need_embeddings = cursor.fetchone()[0]
        print(f"📊 Jobs needing embeddings: {need_embeddings}")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")

# COMMAND ----------

# DBTITLE 1,Step 2: Install sentence-transformers
# MAGIC %pip install -q sentence-transformers

# COMMAND ----------

# DBTITLE 1,Step 3: Run Embeddings Generation
# Step 3: Run the embeddings generation pipeline
import sys
sys.path.append('/Workspace/Users/umehta@mitaoe.ac.in/Job-Hunting-Copilot-Capstone')

print("Running embeddings generation pipeline...\n")
print("This will:")
print("  1. Load sentence-transformers/all-MiniLM-L6-v2 model")
print("  2. Read job postings from Lakebase")
print("  3. Generate 384-dimensional embeddings")
print("  4. Store in job_embeddings table\n")
print("=" * 70)

# Import and run the pipeline
from importlib import reload
import importlib.util

spec = importlib.util.spec_from_file_location(
    "generate_embeddings",
    "/Workspace/Users/umehta@mitaoe.ac.in/Job-Hunting-Copilot-Capstone/mcp_server/02_generate_embeddings.py"
)
embed_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(embed_module)

# Run embeddings generation
try:
    result = embed_module.generate_embeddings(
        batch_size=50,
        limit=None,  # Process all jobs
    )
    
    print("\n" + "=" * 70)
    print("Pipeline Result:")
    print("=" * 70)
    print(f"Status: {result['status']}")
    print(f"Jobs processed: {result['processed']}")
    print(f"Embeddings inserted: {result['inserted']}")
    
except Exception as e:
    print(f"❌ Pipeline failed: {e}")
    import traceback
    traceback.print_exc()

# COMMAND ----------

# DBTITLE 1,Step 4: Verify Embeddings Created
# Step 4: Verify embeddings were created successfully
import psycopg2
import base64
import numpy as np
from databricks.sdk.runtime import dbutils

def get_secret(scope, key):
    secret_bytes = dbutils.secrets.get(scope=scope, key=key)
    try:
        return base64.b64decode(secret_bytes).decode("utf-8")
    except:
        return secret_bytes

print("Verifying embeddings in Lakebase...\n")

try:
    lakebase_url = get_secret("job_hunting", "lakebase_url")
    conn = psycopg2.connect(lakebase_url)
    cursor = conn.cursor()
    
    # Get total count
    cursor.execute("SELECT COUNT(*) FROM job_embeddings;")
    total = cursor.fetchone()[0]
    print(f"✅ Total embeddings in database: {total}\n")
    
    if total > 0:
        # Get sample embeddings with job details
        cursor.execute("""
            SELECT 
                jp.title,
                jp.company,
                jp.location,
                je.model_name,
                array_length(je.embedding, 1) as embedding_dim,
                length(je.chunk_text) as text_length
            FROM job_embeddings je
            JOIN job_postings jp ON je.job_id = jp.job_id
            LIMIT 5;
        """)
        
        print("📋 Sample embeddings:\n")
        for i, row in enumerate(cursor.fetchall(), 1):
            title, company, location, model, dim, text_len = row
            print(f"{i}. {title}")
            print(f"   Company: {company}")
            print(f"   Location: {location}")
            print(f"   Model: {model}")
            print(f"   Embedding dimension: {dim}")
            print(f"   Text length: {text_len} characters")
            print()
        
        # Check coverage
        cursor.execute("""
            SELECT 
                COUNT(*) as total_jobs,
                COUNT(je.job_id) as jobs_with_embeddings,
                COUNT(*) - COUNT(je.job_id) as jobs_missing_embeddings
            FROM job_postings jp
            LEFT JOIN job_embeddings je ON jp.job_id = je.job_id;
        """)
        
        total_jobs, with_emb, missing = cursor.fetchone()
        coverage = (with_emb / total_jobs * 100) if total_jobs > 0 else 0
        
        print("=" * 70)
        print("📊 Coverage Statistics:")
        print("=" * 70)
        print(f"Total jobs: {total_jobs}")
        print(f"Jobs with embeddings: {with_emb}")
        print(f"Jobs missing embeddings: {missing}")
        print(f"Coverage: {coverage:.1f}%\n")
        
        if coverage >= 99:
            print("✅ SUCCESS! Embeddings pipeline is working perfectly!")
        elif missing > 0:
            print(f"⚠️  {missing} jobs still need embeddings (likely missing descriptions)")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")

# COMMAND ----------

# DBTITLE 1,Step 5: Test Semantic Search
# Step 5: Test semantic search query
import psycopg2
import base64
from sentence_transformers import SentenceTransformer
from databricks.sdk.runtime import dbutils

def get_secret(scope, key):
    secret_bytes = dbutils.secrets.get(scope=scope, key=key)
    try:
        return base64.b64decode(secret_bytes).decode("utf-8")
    except:
        return secret_bytes

print("Testing semantic search...\n")

try:
    # Load the same model used for embeddings
    print("Loading model...")
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    
    # Test query
    query = "remote python developer backend API"
    print(f"Query: '{query}'\n")
    
    # Generate query embedding
    query_embedding = model.encode(query).tolist()
    
    # Search in Lakebase
    lakebase_url = get_secret("job_hunting", "lakebase_url")
    conn = psycopg2.connect(lakebase_url)
    cursor = conn.cursor()
    
    # Perform vector similarity search
    cursor.execute("""
        SELECT 
            jp.title,
            jp.company,
            jp.location,
            jp.salary_min,
            jp.salary_max,
            1 - (je.embedding <=> %s::vector) AS similarity
        FROM job_embeddings je
        JOIN job_postings jp ON je.job_id = jp.job_id
        ORDER BY je.embedding <=> %s::vector
        LIMIT 10;
    """, (query_embedding, query_embedding))
    
    results = cursor.fetchall()
    
    print("🔍 Top 10 matching jobs:\n")
    print("=" * 70)
    
    for i, row in enumerate(results, 1):
        title, company, location, sal_min, sal_max, similarity = row
        print(f"{i}. {title}")
        print(f"   Company: {company}")
        print(f"   Location: {location}")
        if sal_min or sal_max:
            print(f"   Salary: £{sal_min or 0:,.0f} - £{sal_max or 0:,.0f}")
        print(f"   Similarity: {similarity:.3f}")
        print()
    
    cursor.close()
    conn.close()
    
    print("=" * 70)
    print("✅ SUCCESS! Semantic search is working!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. ✅ Data pipeline complete (100 jobs ingested)")
    print("2. ✅ Embeddings pipeline complete (jobs vectorized)")
    print("3. ⏭️  Build AI agent with tools (search, explain, save, generate)")
    print("4. ⏭️  Build frontend app")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

# COMMAND ----------

