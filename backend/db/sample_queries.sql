-- Queries using embeddings

-- (Cosine Similarity) Find similar activities to the last 'Run' activity
WITH latest_run AS (
    SELECT embedding
    FROM activities
    WHERE activity_type = 'Run'
    ORDER BY timestamp DESC
    LIMIT 1
)
SELECT id, activity_type, distance, duration, timestamp,
       1 - (embedding <=> (SELECT embedding FROM latest_run)) AS similarity
FROM activities
WHERE activity_type = 'Run'
ORDER BY similarity DESC
LIMIT 5;

-- (Cosine Similarity) Find activities where the athlete performed close to his best performance
WITH best_ride AS (
    SELECT embedding
    FROM activities
    WHERE activity_type = 'Ride'
    ORDER BY distance DESC, duration ASC
    LIMIT 1
)
SELECT id, activity_type, distance, duration, timestamp,
       1 - (embedding <=> (SELECT embedding FROM best_ride)) AS similarity
FROM activities
WHERE activity_type = 'Ride'
ORDER BY similarity DESC
LIMIT 5;

-- (Cosine Similarity) Most Representative activity (fav activity)
WITH avg_embedding AS (
    SELECT AVG(embedding) AS embedding
    FROM activities
)
SELECT id, activity_type, distance, duration, timestamp,
       1 - (embedding <=> (SELECT embedding FROM avg_embedding)) AS similarity
FROM activities
ORDER BY similarity DESC
LIMIT 1;

-- (L2 (Euclidean) Distance) - Closest activities
WITH latest_activity AS (
    SELECT embedding
    FROM activities
	WHERE activity_type = 'Run'
    ORDER BY timestamp DESC
    LIMIT 1
)
SELECT id, activity_type, distance, duration, timestamp,
       (embedding <-> (SELECT embedding FROM latest_activity)) AS l2_distance
FROM activities
ORDER BY l2_distance ASC
LIMIT 5;