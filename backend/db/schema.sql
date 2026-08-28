
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

