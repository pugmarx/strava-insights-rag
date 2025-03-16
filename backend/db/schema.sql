
-- Create the activities table
CREATE TABLE activities (
    id SERIAL PRIMARY KEY,
    activity_id BIGINT UNIQUE,  -- Unique ID from Strava
    user_id VARCHAR(50),
    activity_type VARCHAR(50),
    distance FLOAT,
    duration INT,
    timestamp TIMESTAMP,
    embedding vector(384)  -- Vector storage for embeddings
);
