# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Check Prerequisites
# MAGIC %md
# MAGIC # Test Job Ingestion Pipeline
# MAGIC
# MAGIC This notebook tests the complete flow:
# MAGIC 1. ✅ Check secrets are configured
# MAGIC 2. ✅ Test Adzuna API connection
# MAGIC 3. ✅ Test Lakebase connection
# MAGIC 4. ✅ Run the ingestion pipeline
# MAGIC 5. ✅ Verify jobs loaded into database

# COMMAND ----------

# DBTITLE 1,Step 1: Check Secrets
# Step 1: Check if secrets are configured
from databricks.sdk.runtime import dbutils
import base64

SECRET_SCOPE = "job_hunting"

def check_secret(key):
    try:
        secret = dbutils.secrets.get(scope=SECRET_SCOPE, key=key)
        # Try to decode if base64
        try:
            decoded = base64.b64decode(secret).decode("utf-8")
            return True, "Configured (base64)"
        except:
            return True, "Configured (plaintext)"
    except Exception as e:
        return False, str(e)

print("Checking secrets configuration...\n")
print("=" * 50)

secrets = ["app_id", "app_key", "lakebase_url"]
all_configured = True

for key in secrets:
    exists, status = check_secret(key)
    symbol = "✅" if exists else "❌"
    print(f"{symbol} {SECRET_SCOPE}/{key}: {status}")
    if not exists:
        all_configured = False

print("=" * 50)

if all_configured:
    print("\n✅ All secrets are configured!")
else:
    print("\n❌ Missing secrets! Run setup_secrets.py first:")
    print("   python setup_secrets.py")

# COMMAND ----------

# DBTITLE 1,Step 2: Test Adzuna API
# Step 2: Test Adzuna API connection
import requests
import base64
from databricks.sdk.runtime import dbutils

def get_secret(scope, key):
    secret_bytes = dbutils.secrets.get(scope=scope, key=key)
    try:
        return base64.b64decode(secret_bytes).decode("utf-8")
    except:
        return secret_bytes

print("Testing Adzuna API connection...\n")

try:
    app_id = get_secret("job_hunting", "app_id")
    app_key = get_secret("job_hunting", "app_key")
    
    # Test API call - search for Python jobs in London, page 1
    url = "https://api.adzuna.com/v1/api/jobs/gb/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": "python",
        "results_per_page": 5,
    }
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    results = data.get("results", [])
    total_count = data.get("count", 0)
    
    print("✅ Adzuna API connection successful!")
    print(f"   Total jobs available: {total_count:,}")
    print(f"   Sample results fetched: {len(results)}")
    
    if results:
        print("\n📋 Sample job:")
        sample = results[0]
        print(f"   - Title: {sample.get('title')}")
        print(f"   - Company: {sample.get('company', {}).get('display_name')}")
        print(f"   - Location: {sample.get('location', {}).get('display_name')}")
        print(f"   - Adzuna ID: {sample.get('id')}")
    
except requests.exceptions.HTTPError as e:
    print(f"❌ API Error: {e}")
    print(f"   Status code: {response.status_code}")
    if response.status_code == 401:
        print("   → Check your app_id and app_key credentials")
    elif response.status_code == 429:
        print("   → Rate limit exceeded, try again later")
except Exception as e:
    print(f"❌ Connection failed: {e}")

# COMMAND ----------

# DBTITLE 1,Step 3: Test Lakebase Connection
# Step 3: Test Lakebase database connection
import psycopg2
import base64
from databricks.sdk.runtime import dbutils

def get_secret(scope, key):
    secret_bytes = dbutils.secrets.get(scope=scope, key=key)
    try:
        return base64.b64decode(secret_bytes).decode("utf-8")
    except:
        return secret_bytes

print("Testing Lakebase connection...\n")

try:
    lakebase_url = get_secret("job_hunting", "lakebase_url")
    
    # Connect to Lakebase
    conn = psycopg2.connect(lakebase_url)
    cursor = conn.cursor()
    
    # Test: Check if job_postings table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'job_postings'
        );
    """)
    table_exists = cursor.fetchone()[0]
    
    if table_exists:
        print("✅ Lakebase connection successful!")
        print("✅ job_postings table exists")
        
        # Check current row count
        cursor.execute("SELECT COUNT(*) FROM job_postings;")
        count = cursor.fetchone()[0]
        print(f"   Current job_postings rows: {count}")
    else:
        print("❌ job_postings table does NOT exist")
        print("   Run lakebase_schema.sql first!")
    
    cursor.close()
    conn.close()
    
except psycopg2.OperationalError as e:
    print(f"❌ Connection failed: {e}")
    print("   → Check your Lakebase URL in secrets")
except Exception as e:
    print(f"❌ Error: {e}")

# COMMAND ----------

# DBTITLE 1,Step 4: Run Ingestion Pipeline
# Step 4: Run the ingestion pipeline
print("Running job ingestion pipeline...\n")
print("This will fetch Python developer jobs from Adzuna and load them into Lakebase.\n")

# Import and run the pipeline
import sys
sys.path.append('/Workspace/Users/umehta@mitaoe.ac.in/Job-Hunting-Copilot-Capstone')

from importlib import reload
import importlib.util

spec = importlib.util.spec_from_file_location(
    "ingest_jobs",
    "/Workspace/Users/umehta@mitaoe.ac.in/Job-Hunting-Copilot-Capstone/mcp_server/01_ingest_jobs.py"
)
ingest_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest_module)

# Run ingestion
try:
    result = ingest_module.ingest_jobs(
        country="gb",
        what="python developer",
        where="london",
        max_pages=2,  # Start with just 2 pages for testing
        max_days_old=7
    )
    
    print("\n" + "=" * 70)
    print("Pipeline Result:")
    print("=" * 70)
    print(f"Status: {result['status']}")
    print(f"Jobs fetched: {result['fetched']}")
    print(f"New jobs inserted: {result['inserted']}")
    print(f"Existing jobs updated: {result['updated']}")
    
except Exception as e:
    print(f"❌ Pipeline failed: {e}")
    import traceback
    traceback.print_exc()

# COMMAND ----------

# DBTITLE 1,Step 5: Verify Data in Lakebase
# Step 5: Verify jobs were loaded into Lakebase
import psycopg2
import base64
from databricks.sdk.runtime import dbutils

def get_secret(scope, key):
    secret_bytes = dbutils.secrets.get(scope=scope, key=key)
    try:
        return base64.b64decode(secret_bytes).decode("utf-8")
    except:
        return secret_bytes

print("Verifying data in Lakebase...\n")

try:
    lakebase_url = get_secret("job_hunting", "lakebase_url")
    conn = psycopg2.connect(lakebase_url)
    cursor = conn.cursor()
    
    # Get total count
    cursor.execute("SELECT COUNT(*) FROM job_postings;")
    total = cursor.fetchone()[0]
    print(f"✅ Total jobs in database: {total}\n")
    
    if total > 0:
        # Get sample jobs
        cursor.execute("""
            SELECT title, company, location, salary_min, salary_max, posted_date
            FROM job_postings
            ORDER BY created_at DESC
            LIMIT 5;
        """)
        
        print("📋 Sample jobs (most recently added):\n")
        for i, row in enumerate(cursor.fetchall(), 1):
            title, company, location, sal_min, sal_max, posted = row
            print(f"{i}. {title}")
            print(f"   Company: {company}")
            print(f"   Location: {location}")
            if sal_min or sal_max:
                print(f"   Salary: £{sal_min or 0:,.0f} - £{sal_max or 0:,.0f}")
            print(f"   Posted: {posted}")
            print()
    
    cursor.close()
    conn.close()
    
    print("=" * 70)
    print("✅ SUCCESS! Your job ingestion pipeline is working!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. ✅ Data pipeline complete")
    print("2. ⏭️  Create embeddings pipeline (02_generate_embeddings.py)")
    print("3. ⏭️  Build AI agent with tools")
    print("4. ⏭️  Build frontend app")
    
except Exception as e:
    print(f"❌ Error querying database: {e}")

# COMMAND ----------

