import json
import psycopg2
import os
from sentence_transformers import SentenceTransformer
from datetime import datetime

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Load the embedding model
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# Load Strava activities
with open("activities.json", "r") as file:
    activities = json.load(file)

# Connect to PostgreSQL
conn = psycopg2.connect(
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
)
cur = conn.cursor()

# Function to convert activity into an embedding
def generate_embedding(activity):
    text = f"{activity['name']} {activity['type']} {activity['distance']} meters in {activity['elapsed_time']} seconds"
    print(f"Generating embedding for: {text}")
    # Generate embedding using the model
    return model.encode(text).tolist()

# Function to convert ISO 8601 to PostgreSQL timestamp
def parse_timestamp(iso_date):
    return datetime.fromisoformat(iso_date.replace("Z", "+00:00"))


STRAVA_USER_ID = os.getenv("STRAVA_USER_ID")

for activity in activities:
    embedding = generate_embedding(activity)
    activity_timestamp = parse_timestamp(activity["start_date"])
    
    cur.execute(
        """
        INSERT INTO activities (activity_id, user_id, activity_type, distance, duration, timestamp, embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (activity_id) DO UPDATE SET
            user_id = EXCLUDED.user_id,
            activity_type = EXCLUDED.activity_type,
            distance = EXCLUDED.distance,
            duration = EXCLUDED.duration,
            timestamp = EXCLUDED.timestamp,
            embedding = EXCLUDED.embedding
        """,
        (
            activity["id"],  # Unique Strava activity ID
            STRAVA_USER_ID,
            activity["type"],
            activity["distance"],
            activity["elapsed_time"],
            activity_timestamp,
            embedding,
        ),
    )


# Commit and close connection
conn.commit()
cur.close()
conn.close()

print("- Activities stored successfully! -")