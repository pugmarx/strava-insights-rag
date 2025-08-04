import os
import psycopg2
import pandas as pd
import json
import matplotlib.pyplot as plt
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DB_HOST = os.getenv("POSTGRES_HOST")
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
STRAVA_USER_ID = os.getenv("STRAVA_USER_ID")

# Connect to PostgreSQL
conn = psycopg2.connect(
    host=DB_HOST,
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD
)
cursor = conn.cursor()

# Fetch all activity data
cursor.execute("""
    SELECT id, distance, duration
    FROM activities
    WHERE user_id = %s AND duration > 0
    ORDER BY timestamp ASC
""", (STRAVA_USER_ID,))
rows = cursor.fetchall()

if not rows:
    print("No activities found.")
    exit()

# Prepare full activity DataFrame
# Prepare full activity DataFrame
all_activities = []
for act_id, dist, dur in rows:
    if dur == 0:          # skip corrupt rows
        continue
    speed_kmh = (dist * 3.6) / dur        # m → km, s → h   (dist/1000) / (dur/3600)
    all_activities.append({
        "id": act_id,
        "distance": dist / 1000,          # km
        "duration": dur / 60,             # minutes
        "avg_speed": speed_kmh            # km/h
    })

df_all = pd.DataFrame(all_activities)

# Load anomalies
with open("univariate_anomalies.json") as f:
    anomaly_data = json.load(f)

# Map: metric -> set of outlier IDs
outlier_map = {
    entry["metric"]: set(act["id"] for act in entry["outliers"])
    for entry in anomaly_data["summary"]
}

# Plot each metric
metrics = ["distance", "duration", "avg_speed"]
units = {"distance": "km", "duration": "min", "avg_speed": "km/h"}

for metric in metrics:
    plt.figure(figsize=(10, 5))
    plt.title(f"{metric.capitalize()} — All Activities (with anomalies)")
    plt.xlabel("Activity Index")
    plt.ylabel(f"{metric} ({units[metric]})")

    values = df_all[metric].tolist()
    ids = df_all["id"].tolist()

    # Plot normal points
    for i, val in enumerate(values):
        if ids[i] not in outlier_map.get(metric, set()):
            plt.scatter(i, val, color="blue", s=15)

    # Plot outliers
    for i, val in enumerate(values):
        if ids[i] in outlier_map.get(metric, set()):
            plt.scatter(i, val, color="red", s=30)
            plt.annotate(str(ids[i]), (i, val), fontsize=8, xytext=(5, 3), textcoords="offset points")

    plt.grid(True)
    plt.tight_layout()
    filename = f"{metric}_anomalies_full.png"
    plt.savefig(filename)
    plt.close()
    print(f"Saved: {filename}")

# Cleanup
cursor.close()
conn.close()
