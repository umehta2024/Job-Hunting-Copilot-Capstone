# Job Hunting Copilot - Semantic Job Search System

A Databricks-powered job search application that enables semantic search over job postings using vector embeddings and pgvector.

## 🎯 Architecture Overview

This system provides:
- **Data ingestion** from Adzuna Jobs API
- **Vector embeddings** for semantic search over job descriptions (384-dim, NO LLM!)
- **REST API** for searching jobs via natural language
- **Lakebase (Postgres)** storage with pgvector for fast similarity search
- **Flask web interface** with job cards and filtering

## ⚡ Quick Start: End-to-End Example

### **Step 1: Ingest Job Postings**
```bash
python 01_ingest_jobs.py
# Fetches jobs from Adzuna API (London, Python, £50k+)
# Stores in job_postings table
```

### **Step 2: Generate Embeddings**
```bash
python 02_generate_embeddings.py
# Creates 384-dim vectors using sentence-transformers
# Stores in job_embeddings table with pgvector
```

### **Step 3: Run the Flask App**
```bash
python app.py
# App runs at http://localhost:8080
# Open browser and start searching!
```

## 🔍 API Endpoints

### **Search Jobs (Semantic)**
```bash
curl -X POST http://localhost:8080/jobs/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Python backend developer with microservices",
    "location": "London",
    "min_salary": 70000,
    "top_k": 10
  }'

# Response:
# {
#   "results": [
#     {
#       "job_id": 123,
#       "title": "Senior Python Engineer",
#       "company": "Tech Corp",
#       "location": "London",
#       "salary_min": 70000,
#       "salary_max": 90000,
#       "similarity": 0.89,
#       "url": "https://..."
#     },
#     ...
#   ],
#   "count": 10
# }
```

### **List All Jobs**
```bash
curl "http://localhost:8080/jobs?limit=20&location=London&min_salary=70000"
```

### **Get Job Details**
```bash
curl "http://localhost:8080/jobs/123"
```

### **Save Job to Favorites**
```bash
curl -X POST http://localhost:8080/jobs/save \
  -H "Content-Type: application/json" \
  -d '{"job_id": 123, "user_id": 1, "notes": "Great fit!"}'
```

### **Get Saved Jobs**
```bash
curl "http://localhost:8080/jobs/saved?user_id=1"
```

## 🗄️ Database Schema

### **Tables:**
- `job_postings` - Job metadata (title, company, location, salary, description, URL)
- `job_embeddings` - 384-dim vectors with pgvector extension
- `saved_jobs` - User favorites (job_id, user_id, notes, saved_at)

### **Search Query:**
```sql
SELECT 
  jp.*,
  1 - (je.embedding <=> %s::vector) AS similarity
FROM job_postings jp
JOIN job_embeddings je ON jp.job_id = je.job_id
WHERE jp.location ILIKE %s
  AND jp.salary_min >= %s
ORDER BY je.embedding <=> %s::vector
LIMIT 10;
```

## 📦 Dependencies

```
databricks-sdk>=0.30.0
psycopg2-binary>=2.9.9
sqlalchemy>=2.0.30
flask>=3.0.3
sentence-transformers>=2.2.0
requests>=2.32.3
```

## 🚀 Deployment (Databricks Apps)

1. **Configure secrets:**
   ```bash
   python setup_secrets.py
   ```

2. **Update app.yaml** with your Lakebase connection:
   ```yaml
   env:
     - name: LAKEBASE_SECRET_SCOPE
       value: "job_hunting"
     - name: LAKEBASE_SECRET_KEY
       value: "lakebase_url"
   ```

3. **Deploy through Databricks Apps UI** or CLI:
   ```bash
   databricks apps deploy <app-name>
   ```

## 🧪 Testing

Run the test scripts to verify:
```bash
# Test ingestion
python test_ingestion.py

# Test embeddings pipeline
python test_embeddings_pipeline.py

# Test vector search
python test_vector_search.py
```

## 💡 Key Features

✅ **NO LLM required** - Pure vector similarity search  
✅ **Fast pgvector search** - Cosine similarity with `<=>` operator  
✅ **Semantic matching** - "Python developer" matches "Backend Engineer"  
✅ **Location & salary filters** - Combine semantic + structured filters  
✅ **Save favorites** - Track interesting jobs  
✅ **Beautiful UI** - Job cards with similarity scores  

## 🔧 Configuration

### **Environment Variables:**
- `LAKEBASE_SECRET_SCOPE` - Databricks secret scope name
- `LAKEBASE_SECRET_KEY` - Secret key for Lakebase URL
- `ADZUNA_APP_ID` - Adzuna API app ID (for ingestion)
- `ADZUNA_APP_KEY` - Adzuna API app key (for ingestion)

## 📊 Current Data

- **100 jobs** ingested from Adzuna
- **Location:** London, UK
- **Keywords:** Python, Backend, Developer
- **Salary:** £50,000+
- **Embeddings:** 384-dim vectors (all-MiniLM-L6-v2)

## 🎨 Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | Flask (Python) |
| **Database** | Lakebase Postgres + pgvector |
| **Embeddings** | sentence-transformers (all-MiniLM-L6-v2) |
| **Frontend** | HTML/CSS/JavaScript |
| **Deployment** | Databricks Apps |
| **Data Source** | Adzuna Jobs API |

## 📝 Project Structure

```
Job-Hunting-Copilot-Capstone/
├── app.py                         # Flask API
├── app.yaml                       # Databricks App config
├── lakebase.py                    # Database connection helper
├── requirements.txt               # Python dependencies
├── templates/
│   └── index.html                # Job search UI
├── 01_ingest_jobs.py             # Adzuna API ingestion
├── 02_generate_embeddings.py     # Vector generation
├── setup_secrets.py              # Secret configuration
├── test_ingestion.py             # Test ingestion
├── test_embeddings_pipeline.py   # Test embeddings
└── test_vector_search.py         # Test search
```

## 🔒 Security

- All secrets stored in Databricks Secret Scope
- Lakebase URL base64-encoded
- OAuth tokens for API authentication
- No hardcoded credentials

## 📈 Future Enhancements

- [ ] Add more job sources (LinkedIn, Indeed, etc.)
- [ ] User authentication
- [ ] Job alerts/notifications
- [ ] Application tracking
- [ ] Resume matching
- [ ] Interview scheduler integration

---

**Built with ❤️ using Databricks, Lakebase, and pgvector**
