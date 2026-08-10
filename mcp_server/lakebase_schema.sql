-- ============================================
-- Job Hunting Copilot - Lakebase Schema
-- ============================================
-- PostgreSQL schema for job hunting application
-- Run this script against your Lakebase database

-- Enable pgvector extension (required for embeddings)
CREATE EXTENSION IF NOT EXISTS vector;

-- Drop existing tables (in reverse order to handle foreign keys)
DROP TABLE IF EXISTS interview_notes CASCADE;
DROP TABLE IF EXISTS contacts CASCADE;
DROP TABLE IF EXISTS saved_jobs CASCADE;
DROP TABLE IF EXISTS applications CASCADE;
DROP TABLE IF EXISTS job_embeddings CASCADE;
DROP TABLE IF EXISTS skills CASCADE;
DROP TABLE IF EXISTS job_postings CASCADE;
DROP TABLE IF EXISTS profiles CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- ============================================
-- 1. USERS TABLE
-- ============================================
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);

-- ============================================
-- 2. PROFILES TABLE
-- ============================================
CREATE TABLE profiles (
    profile_id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL,
    full_name VARCHAR(255),
    phone VARCHAR(20),
    location VARCHAR(255),
    linkedin_url VARCHAR(500),
    github_url VARCHAR(500),
    portfolio_url VARCHAR(500),
    bio TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_profiles_user_id ON profiles(user_id);

-- ============================================
-- 3. SKILLS TABLE
-- ============================================
CREATE TABLE skills (
    skill_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    skill_name VARCHAR(100) NOT NULL,
    proficiency_level VARCHAR(20) CHECK (proficiency_level IN ('beginner', 'intermediate', 'advanced', 'expert')),
    years_of_experience DECIMAL(3,1),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_skills_user_id ON skills(user_id);
CREATE INDEX idx_skills_name ON skills(skill_name);

-- Add unique constraint for ON CONFLICT upsert in POST /profile
DO $
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'skills_user_id_skill_name_key'
    ) THEN
        ALTER TABLE skills
            ADD CONSTRAINT skills_user_id_skill_name_key UNIQUE (user_id, skill_name);
    END IF;
END $;

-- ============================================
-- 4. JOB_POSTINGS TABLE
-- ============================================
CREATE TABLE job_postings (
    job_id SERIAL PRIMARY KEY,
    adzuna_id VARCHAR(100) UNIQUE,
    title VARCHAR(500) NOT NULL,
    company VARCHAR(255),
    location VARCHAR(255),
    salary_min DECIMAL(10,2),
    salary_max DECIMAL(10,2),
    description TEXT,
    url VARCHAR(1000),
    posted_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_job_postings_adzuna_id ON job_postings(adzuna_id);
CREATE INDEX idx_job_postings_company ON job_postings(company);
CREATE INDEX idx_job_postings_location ON job_postings(location);
CREATE INDEX idx_job_postings_posted_date ON job_postings(posted_date);

-- ============================================
-- 5. APPLICATIONS TABLE
-- ============================================
CREATE TABLE applications (
    application_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'applied' CHECK (status IN ('applied', 'interviewing', 'offered', 'rejected', 'accepted', 'withdrawn')),
    applied_date DATE DEFAULT CURRENT_DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES job_postings(job_id) ON DELETE CASCADE,
    UNIQUE(user_id, job_id)
);

CREATE INDEX idx_applications_user_id ON applications(user_id);
CREATE INDEX idx_applications_job_id ON applications(job_id);
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_applications_applied_date ON applications(applied_date);

-- ============================================
-- 6. SAVED_JOBS TABLE
-- ============================================
CREATE TABLE saved_jobs (
    saved_job_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES job_postings(job_id) ON DELETE CASCADE,
    UNIQUE(user_id, job_id)
);

CREATE INDEX idx_saved_jobs_user_id ON saved_jobs(user_id);
CREATE INDEX idx_saved_jobs_job_id ON saved_jobs(job_id);

-- ============================================
-- 7. INTERVIEW_NOTES TABLE
-- ============================================
CREATE TABLE interview_notes (
    note_id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL,
    interview_date DATE,
    interview_type VARCHAR(20) CHECK (interview_type IN ('phone', 'video', 'onsite', 'technical', 'behavioral')),
    interviewer_name VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (application_id) REFERENCES applications(application_id) ON DELETE CASCADE
);

CREATE INDEX idx_interview_notes_application_id ON interview_notes(application_id);
CREATE INDEX idx_interview_notes_date ON interview_notes(interview_date);

-- ============================================
-- 8. CONTACTS TABLE
-- ============================================
CREATE TABLE contacts (
    contact_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    company VARCHAR(255),
    title VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(20),
    linkedin_url VARCHAR(500),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_contacts_user_id ON contacts(user_id);
CREATE INDEX idx_contacts_company ON contacts(company);

-- ============================================
-- SAMPLE DATA (Optional - for testing)
-- ============================================

-- Insert test user with user_id = 1 (with all permissions - active user)
INSERT INTO users (user_id, email, password_hash, is_active) 
VALUES (1, 'test@example.com', 'hashed_password_here', true)
ON CONFLICT (user_id) DO NOTHING;

-- Reset sequence to continue from user_id = 2 if needed
SELECT setval('users_user_id_seq', (SELECT MAX(user_id) FROM users));

-- Insert test profile with preferences
INSERT INTO profiles (user_id, full_name, location, phone, linkedin_url, github_url, bio, preferences)
VALUES (
    1, 
    'Test User', 
    'San Francisco, CA',
    '555-123-4567',
    'https://linkedin.com/in/testuser',
    'https://github.com/testuser',
    'Software Engineer with 5 years of experience looking for Python/ML opportunities',
    '{"preferred_location": "San Francisco", "preferred_category": "IT Jobs", "min_salary": 90000, "remote_only": false}'::jsonb
)
ON CONFLICT (user_id) DO NOTHING;

-- Insert test skills
INSERT INTO skills (user_id, skill_name, proficiency_level, years_of_experience)
VALUES 
    (1, 'Python', 'expert', 5.0),
    (1, 'SQL', 'advanced', 4.5),
    (1, 'Machine Learning', 'advanced', 3.0),
    (1, 'PostgreSQL', 'advanced', 4.0),
    (1, 'Flask', 'advanced', 3.5)
ON CONFLICT (user_id, skill_name) DO NOTHING;

-- Success message
SELECT 'Schema created successfully! All 8 tables are ready.' AS status;
