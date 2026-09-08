
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the activities table
CREATE TABLE IF NOT EXISTS activities (
    id SERIAL PRIMARY KEY,
    activity_id BIGINT UNIQUE,  -- Unique ID from Strava
    user_id VARCHAR(50),
    activity_type VARCHAR(50),
    distance FLOAT,
    duration INT,
    elevation_gain FLOAT DEFAULT 0,  -- Total elevation gain in meters
    timestamp TIMESTAMP,
    embedding vector(384)  -- Vector storage for embeddings
);

-- Migration for existing databases
ALTER TABLE activities ADD COLUMN IF NOT EXISTS elevation_gain FLOAT DEFAULT 0;

-- Create table to persist Strava OAuth tokens across container restarts
CREATE TABLE IF NOT EXISTS strava_tokens (
    id INT PRIMARY KEY DEFAULT 1,
    athlete_id VARCHAR(50),
    access_token TEXT,
    refresh_token TEXT,
    expires_at BIGINT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT single_row CHECK (id = 1)
);

-- Create table for semantic vector query caching across container restarts
CREATE TABLE IF NOT EXISTS query_cache (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    query_type VARCHAR(20) DEFAULT 'rag',
    target_year INT,
    is_historical BOOLEAN DEFAULT FALSE,
    embedding vector(384) NOT NULL,
    response TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS query_cache_embedding_idx 
ON query_cache USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 20);

-- Create table to log queries, failure reasons, and performance metrics
CREATE TABLE IF NOT EXISTS query_logs (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    approach VARCHAR(30) DEFAULT 'rag',
    status VARCHAR(30) NOT NULL,  -- SUCCESS, NO_RESULTS, ERROR, UNRECOGNIZED
    retrieved_count INT DEFAULT 0,
    error_message TEXT,
    response_preview TEXT,
    latency_ms INT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS query_logs_status_idx ON query_logs (status);
CREATE INDEX IF NOT EXISTS query_logs_created_at_idx ON query_logs (created_at);

-- Row Level Security (RLS) Enablement
-- Blocks public PostgREST HTTP access in Supabase while preserving direct database connections for backend
ALTER TABLE IF EXISTS activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS strava_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS query_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS query_logs ENABLE ROW LEVEL SECURITY;


