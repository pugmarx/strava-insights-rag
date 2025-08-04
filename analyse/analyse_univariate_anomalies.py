import os
import psycopg2
from dotenv import load_dotenv
import numpy as np
import json
from datetime import datetime
from tqdm import tqdm

# Load environment variables
load_dotenv()

POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
STRAVA_USER_ID = os.getenv("STRAVA_USER_ID")

# Connect to DB
conn = psycopg2.connect(
    host=POSTGRES_HOST,
    dbname=POSTGRES_DB,
    user=POSTGRES_USER,
    password=POSTGRES_PASSWORD
)
cursor = conn.cursor()

# Fetch basic activity data
cursor.execute("""
    SELECT id, activity_type, distance, duration, timestamp
    FROM activities
    WHERE user_id = %s
    ORDER BY timestamp ASC
""", (STRAVA_USER_ID,))
rows = cursor.fetchall()

if not rows:
    print("WARNING: No activities found in the DB.")
    exit()

# Prepare metrics
activities = []
for r in rows:
    act_id, act_type, dist, dur, ts = r
    if dur == 0:
        continue  # skip corrupt entries
    activities.append({
        "id": act_id,
        "type": act_type,
        "distance": dist,
        "duration": dur,
        "timestamp": ts.isoformat(),
        "avg_speed": dist / dur
    })

print(f"INFO: Loaded {len(activities)} activities.")

# Helper: IQR detection
def detect_outliers(metric_name, values):
    q1 = np.percentile(values, 25)
    q3 = np.percentile(values, 75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    outlier_indices = [i for i, v in enumerate(values) if v < lower or v > upper]
    return {
        "metric": metric_name,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "lower": lower,
        "upper": upper,
        "outliers": [activities[i] for i in outlier_indices]
    }

# Run analysis
distance_values = [a["distance"] for a in activities]
duration_values = [a["duration"] for a in activities]
speed_values = [a["avg_speed"] for a in activities]

results = [
    detect_outliers("distance", distance_values),
    detect_outliers("duration", duration_values),
    detect_outliers("avg_speed", speed_values)
]

# Print summary
for result in results:
    print(f"\nANALYSIS: {result['metric'].capitalize()} Outliers:")
    if result["outliers"]:
        for a in result["outliers"]:
            print(f" - [{a['id']}] {a['type']} -- {result['metric']} = {round(a[result['metric']], 2)}")
    else:
        print(" - None")

# Save results to JSON
with open("univariate_anomalies.json", "w") as f:
    json.dump({
        "generated_at": datetime.utcnow().isoformat(),
        "summary": results
    }, f, indent=2)

print("\nSUCCESS: Results saved to univariate_anomalies.json")

# Cleanup
cursor.close()
conn.close()
