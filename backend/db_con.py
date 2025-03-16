
import psycopg2
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Connect to PostgreSQL
conn = psycopg2.connect(
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
)
cur = conn.cursor()

# # Function to convert activity into an embedding
# def generate_embedding(activity):
#     text = f"{activity['name']} {activity['type']} {activity['distance']} meters in {activity['elapsed_time']} seconds"
#     return model.encode(text).tolist()

# # Function to convert ISO 8601 to PostgreSQL timestamp
# def parse_timestamp(iso_date):
#     return datetime.fromisoformat(iso_date.replace("Z", "+00:00"))

# # Insert data into PostgreSQL
# for activity in activities:
#     embedding = generate_embedding(activity)
#     activity_timestamp = parse_timestamp(activity["start_date"])  # Convert ISO date

#     cur.execute(
#         """
#         INSERT INTO activities (user_id, activity_type, distance, duration, timestamp, embedding)
#         VALUES (%s, %s, %s, %s, %s, %s)
#         """,
#         (
#             "6654500",  
#             activity["type"],
#             activity["distance"],
#             activity["elapsed_time"],
#             activity_timestamp,  # Corrected timestamp storage
#             embedding,
#         ),
#     )

# Commit and close connection
conn.commit()
cur.close()
conn.close()

print("- DB conn successful! -")