import os
import json
from datetime import datetime
import requests
import psycopg2
from dotenv import load_dotenv

from token_manager import get_valid_access_token, get_db_connection, ATHLETE_ID
from sql_rag import compute_embedding
from cache_manager import invalidate_cache_for_year

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
    """Generate textual summary for embedding creation using active moving time."""
    name = activity.get("name", "Activity")
    act_type = activity.get("type", "Workout")
    distance = activity.get("distance", 0)
    # Prefer moving_time for active workout effort representation
    moving_time = activity.get("moving_time") or activity.get("elapsed_time", 0)
    elevation = activity.get("total_elevation_gain", 0)
    elev_str = f" with {elevation:.0f}m elevation gain" if elevation and elevation > 0 else ""
    return f"{name} {act_type} {distance} meters{elev_str} in {moving_time} seconds"


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
    """Generate embedding with fastembed and upsert activity into PostgreSQL with moving_time and summary_polyline."""
    conn = get_db_connection()
    if not conn:
        raise ConnectionError("Could not connect to database to save activity")

    text = format_activity_text(activity_data)
    embedding = compute_embedding(text)
    timestamp = parse_strava_timestamp(activity_data.get("start_date"))
    user_id = str(activity_data.get("athlete", {}).get("id") or ATHLETE_ID or "user")
    elevation_gain = float(activity_data.get("total_elevation_gain") or 0.0)

    # Active moving duration (matches Strava UI speed & pace)
    moving_duration = int(activity_data.get("moving_time") or activity_data.get("elapsed_time") or 0)
    total_elapsed = int(activity_data.get("elapsed_time") or moving_duration)

    # GPS summary polyline
    map_obj = activity_data.get("map") or {}
    summary_polyline = map_obj.get("summary_polyline") if isinstance(map_obj, dict) else None

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO activities (activity_id, user_id, activity_type, distance, duration, elevation_gain, elapsed_time, summary_polyline, timestamp, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (activity_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    activity_type = EXCLUDED.activity_type,
                    distance = EXCLUDED.distance,
                    duration = EXCLUDED.duration,
                    elevation_gain = EXCLUDED.elevation_gain,
                    elapsed_time = EXCLUDED.elapsed_time,
                    summary_polyline = COALESCE(EXCLUDED.summary_polyline, activities.summary_polyline),
                    timestamp = EXCLUDED.timestamp,
                    embedding = EXCLUDED.embedding
            """, (
                activity_data["id"],
                user_id,
                activity_data.get("type", "Workout"),
                activity_data.get("distance", 0.0),
                moving_duration,
                elevation_gain,
                total_elapsed,
                summary_polyline,
                timestamp,
                embedding
            ))
            conn.commit()
            if timestamp and hasattr(timestamp, "year"):
                invalidate_cache_for_year(timestamp.year)
            else:
                invalidate_cache_for_year(datetime.now().year)
            return True
    finally:
        conn.close()


def get_activity_streams(activity_id):
    """
    Retrieve detailed GPS streams (velocity, altitude, coordinates, time, distance)
    for an activity. Uses database caching in `activity_streams` table to prevent
    repeated Strava API calls.
    """
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT streams_json FROM activity_streams WHERE activity_id = %s", (activity_id,))
                row = cur.fetchone()
                if row and row[0]:
                    data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                    return data
        except Exception as e:
            print(f"[StravaService] Error reading cached streams for {activity_id}: {e}")
        finally:
            conn.close()

    # Fetch from Strava API v3
    token = get_valid_access_token()
    if not token:
        raise RuntimeError("No valid Strava access token available.")

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{STRAVA_API_BASE}/activities/{activity_id}/streams"
    params = {
        "keys": "latlng,velocity_smooth,altitude,time,distance",
        "key_by_type": "true"
    }
    res = requests.get(url, headers=headers, params=params, timeout=20)
    if res.status_code != 200:
        if res.status_code == 404:
            return {"activity_id": activity_id, "has_streams": False, "points": []}
        raise RuntimeError(f"Strava streams error: {res.status_code} {res.text}")

    raw_streams = res.json()
    latlngs = raw_streams.get("latlng", {}).get("data", [])
    velocities = raw_streams.get("velocity_smooth", {}).get("data", [])
    altitudes = raw_streams.get("altitude", {}).get("data", [])
    times = raw_streams.get("time", {}).get("data", [])
    distances = raw_streams.get("distance", {}).get("data", [])

    points = []
    num_pts = min(len(latlngs), len(velocities)) if latlngs else 0
    max_speed_kmh = 0.0
    max_speed_idx = 0
    peak_alt_m = -9999.0
    peak_alt_idx = 0

    for i in range(num_pts):
        coord = latlngs[i] if i < len(latlngs) else None
        if not coord or len(coord) != 2:
            continue
        v_ms = velocities[i] if i < len(velocities) else 0.0
        v_kmh = round(v_ms * 3.6, 2)
        alt = round(altitudes[i], 1) if i < len(altitudes) else 0.0
        t_sec = times[i] if i < len(times) else 0
        d_m = round(distances[i], 1) if i < len(distances) else 0.0

        if v_kmh > max_speed_kmh:
            max_speed_kmh = v_kmh
            max_speed_idx = len(points)

        if alt > peak_alt_m:
            peak_alt_m = alt
            peak_alt_idx = len(points)

        points.append({
            "lat": coord[0],
            "lng": coord[1],
            "speed_kmh": v_kmh,
            "altitude_m": alt,
            "time_sec": t_sec,
            "distance_m": d_m
        })

    result = {
        "activity_id": activity_id,
        "has_streams": len(points) > 0,
        "point_count": len(points),
        "max_speed_kmh": max_speed_kmh,
        "peak_altitude_m": peak_alt_m if peak_alt_m != -9999.0 else 0.0,
        "top_speed_point": points[max_speed_idx] if points else None,
        "peak_altitude_point": points[peak_alt_idx] if points else None,
        "start_point": points[0] if points else None,
        "finish_point": points[-1] if points else None,
        "points": points
    }

    # Cache in PostgreSQL activity_streams table
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO activity_streams (activity_id, streams_json)
                    VALUES (%s, %s)
                    ON CONFLICT (activity_id) DO UPDATE SET
                        streams_json = EXCLUDED.streams_json,
                        created_at = CURRENT_TIMESTAMP
                """, (activity_id, json.dumps(result)))
                conn.commit()
        except Exception as e:
            print(f"[StravaService] Error caching streams in DB for {activity_id}: {e}")
        finally:
            conn.close()

    return result



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
            invalidate_cache_for_year(datetime.now().year)
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
