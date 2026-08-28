import os
from datetime import datetime
import requests
import psycopg2
from dotenv import load_dotenv

from token_manager import get_valid_access_token, get_db_connection, ATHLETE_ID
from sql_rag import compute_embedding

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(project_root, ".env"))
load_dotenv()

STRAVA_API_BASE = "https://www.strava.com/api/v3"


def parse_strava_timestamp(iso_date_str):
    """Convert Strava ISO 8601 string to Python datetime object."""
    if not iso_date_str:
        return datetime.utcnow()
    # Normalize Z to +00:00
    cleaned = iso_date_str.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def format_activity_text(activity):
    """Generate textual summary for embedding creation."""
    name = activity.get("name", "Activity")
    act_type = activity.get("type", "Workout")
    distance = activity.get("distance", 0)
    elapsed_time = activity.get("elapsed_time", 0)
    elevation = activity.get("total_elevation_gain", 0)
    elev_str = f" with {elevation:.0f}m elevation gain" if elevation and elevation > 0 else ""
    return f"{name} {act_type} {distance} meters{elev_str} in {elapsed_time} seconds"


def fetch_activity_from_strava(activity_id):
    """Fetch full activity details by ID from Strava API."""
    token = get_valid_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{STRAVA_API_BASE}/activities/{activity_id}"
    
    res = requests.get(url, headers=headers, timeout=20)
    if res.status_code != 200:
        raise RuntimeError(f"Failed to fetch activity {activity_id} from Strava: {res.status_code} {res.text}")
    
    return res.json()


def save_activity_to_db(activity_data):
    """Generate embedding with fastembed and upsert activity into PostgreSQL."""
    conn = get_db_connection()
    if not conn:
        raise ConnectionError("Could not connect to database to save activity")

    text = format_activity_text(activity_data)
    embedding = compute_embedding(text)
    timestamp = parse_strava_timestamp(activity_data.get("start_date"))
    user_id = str(activity_data.get("athlete", {}).get("id") or ATHLETE_ID or "user")
    elevation_gain = float(activity_data.get("total_elevation_gain") or 0.0)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO activities (activity_id, user_id, activity_type, distance, duration, elevation_gain, timestamp, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (activity_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    activity_type = EXCLUDED.activity_type,
                    distance = EXCLUDED.distance,
                    duration = EXCLUDED.duration,
                    elevation_gain = EXCLUDED.elevation_gain,
                    timestamp = EXCLUDED.timestamp,
                    embedding = EXCLUDED.embedding
            """, (
                activity_data["id"],
                user_id,
                activity_data.get("type", "Workout"),
                activity_data.get("distance", 0.0),
                activity_data.get("elapsed_time", 0),
                elevation_gain,
                timestamp,
                embedding
            ))
            conn.commit()
            return True
    finally:
        conn.close()


def sync_single_activity(activity_id):
    """Fetch from Strava, embed, and store in database."""
    print(f"[StravaService] Syncing activity {activity_id}...")
    activity_data = fetch_activity_from_strava(activity_id)
    save_activity_to_db(activity_data)
    print(f"[StravaService] Successfully embedded & saved activity {activity_id}: '{activity_data.get('name')}'")
    return activity_data


def delete_activity(activity_id):
    """Remove an activity from PostgreSQL upon deletion event."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM activities WHERE activity_id = %s", (activity_id,))
            conn.commit()
            print(f"[StravaService] Deleted activity {activity_id} from database.")
            return True
    finally:
        conn.close()


def get_latest_activity_timestamp():
    """Retrieve the most recent activity timestamp from the database."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(timestamp) FROM activities")
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
    finally:
        conn.close()
    return None


def sync_incremental(limit=100):
    """
    Fetch and embed all activities newer than the newest activity currently in the database.
    If database is empty, fetches the most recent `limit` activities.
    """
    token = get_valid_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{STRAVA_API_BASE}/athlete/activities"

    latest_ts = get_latest_activity_timestamp()
    params = {"per_page": min(limit, 100), "page": 1}

    if latest_ts:
        # Convert timestamp to epoch seconds for Strava 'after' filter
        epoch_after = int(latest_ts.timestamp())
        params["after"] = epoch_after
        print(f"[StravaService] Fetching activities after {latest_ts} (epoch: {epoch_after})...")
    else:
        print(f"[StravaService] No existing activities in DB. Fetching latest {limit} activities...")

    res = requests.get(url, headers=headers, params=params, timeout=25)
    if res.status_code != 200:
        raise RuntimeError(f"Error fetching athlete activities from Strava: {res.status_code} {res.text}")

    activities = res.json()
    if not isinstance(activities, list):
        raise ValueError(f"Unexpected response format from Strava: {activities}")

    synced_count = 0
    for act in activities:
        try:
            save_activity_to_db(act)
            synced_count += 1
        except Exception as e:
            print(f"[StravaService] Error saving activity {act.get('id')}: {e}")

    print(f"[StravaService] Incremental sync finished. Synced {synced_count} activities.")
    return {
        "status": "success",
        "synced_count": synced_count,
        "latest_timestamp": latest_ts.isoformat() if latest_ts else None
    }
