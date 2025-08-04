import os
import psycopg2
import pandas as pd
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DB_HOST = os.getenv("POSTGRES_HOST")
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
STRAVA_USER_ID = os.getenv("STRAVA_USER_ID")

# Connect to DB
conn = psycopg2.connect(
    host=DB_HOST,
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD
)
cursor = conn.cursor()

# Fetch all activity data
cursor.execute("""
    SELECT id, activity_type, distance, duration
    FROM activities
    WHERE user_id = %s AND duration > 0
    ORDER BY timestamp ASC
""", (STRAVA_USER_ID,))
rows = cursor.fetchall()
cursor.close()
conn.close()

# Prepare activity DataFrame
activities = []
for r in rows:
    act_id, act_type, dist, dur = r
    speed_kmh = (dist * 3.6) / dur if dur else 0
    activities.append({
        "id": act_id,
        "activity_type": act_type,
        "distance": dist / 1000,     # meters to km
        "duration": dur / 60,        # seconds to minutes
        "avg_speed": speed_kmh       # km/h
    })

df = pd.DataFrame(activities)

# Detect anomalies using IQR method
summary = []
metrics = ["distance", "duration", "avg_speed"]

for activity_type, group in df.groupby("activity_type"):
    for metric in metrics:
        values = group[metric]
        Q1 = values.quantile(0.25)
        Q3 = values.quantile(0.75)
        IQR = Q3 - Q1
        lower = Q1 - 1.5 * IQR
        upper = Q3 + 1.5 * IQR

        outliers = group[(values < lower) | (values > upper)]
        summary.append({
            "activity_type": activity_type,
            "metric": metric,
            "outliers": outliers.to_dict(orient="records")
        })

# Save result to JSON
with open("univariate_anomalies.json", "w") as f:
    json.dump({"summary": summary}, f, indent=2)

print("Saved: univariate_anomalies.json")
