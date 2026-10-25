import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
load_dotenv(os.path.join(project_root, ".env"))
load_dotenv()

from token_manager import get_db_connection
from sql_rag import compute_embedding
from cache_manager import invalidate_cache_for_year

try:
    from garminconnect import Garmin
except ImportError:
    Garmin = None

_sync_lock = threading.Lock()
_last_sync_time = None
_is_syncing = False


GARMIN_TYPE_MAP = {
    "cycling": "Ride",
    "road_biking": "Ride",
    "gravel_cycling": "Ride",
    "mountain_biking": "Ride",
    "running": "Run",
    "treadmill_running": "Run",
    "trail_running": "Run",
    "hiking": "Hike",
    "walking": "Walk",
    "strength_training": "WeightTraining",
    "weight_training": "WeightTraining",
    "fitness_equipment": "Workout",
    "cardio_training": "Workout",
}

TOKEN_DIR = Path(project_root) / ".garmin_tokens"


def encode_coords_to_polyline(coords):
    """Encode a list of (lat, lon) tuples into Google Encoded Polyline format."""
    if not coords:
        return None
    result = []
    prev_lat, prev_lng = 0, 0
    for lat, lng in coords:
        lat_e5 = round(lat * 1e5)
        lng_e5 = round(lng * 1e5)
        d_lat = lat_e5 - prev_lat
        d_lng = lng_e5 - prev_lng
        prev_lat, prev_lng = lat_e5, lng_e5
        for val in (d_lat, d_lng):
            val = ~(val << 1) if val < 0 else (val << 1)
            while val >= 0x20:
                result.append(chr((0x20 | (val & 0x1F)) + 63))
                val >>= 5
            result.append(chr(val + 63))
    return "".join(result)


def get_garmin_client():
    """Initialize Garmin client from cached session tokens or credentials."""
    if Garmin is None:
        raise RuntimeError("garminconnect is not installed.")

    client = Garmin()
    if TOKEN_DIR.exists() and any(TOKEN_DIR.iterdir()):
        try:
            client.login(str(TOKEN_DIR))
            return client
        except Exception as e:
            print(f"[GarminService] Cached token login failed ({e}), trying credentials...")

    email = os.getenv("GARMIN_EMAIL", "").strip()
    password = os.getenv("GARMIN_PASSWORD", "").strip()
    if not email or not password:
        raise RuntimeError("No valid Garmin session tokens or credentials found in .env.")

    client = Garmin(email=email, password=password)
    client.login()
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    client.garth.dump(str(TOKEN_DIR))
    return client


def format_activity_text(name, act_type, distance, elevation, moving_time):
    """Generate textual summary for FastEmbed embedding creation."""
    elev_str = f" with {elevation:.0f}m elevation gain" if elevation and elevation > 0 else ""
    return f"{name} {act_type} {distance:.0f} meters{elev_str} in {moving_time} seconds"


def parse_garmin_timestamp(start_time_str):
    """Parse Garmin ISO / date string (e.g. '2026-10-09 18:12:29')."""
    if not start_time_str:
        return datetime.utcnow()
    # Replace space with T if needed
    cleaned = start_time_str.strip()
    if " " in cleaned:
        cleaned = cleaned.replace(" ", "T")
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    elif not any(x in cleaned for x in ("+", "-")) or len(cleaned) <= 19:
        # Naive local timestamp
        return datetime.fromisoformat(cleaned)
    return datetime.fromisoformat(cleaned)


def save_garmin_activity_to_db(garmin_act, client=None):
    """Normalize Garmin activity JSON and upsert into PostgreSQL activities table with embeddings."""
    conn = get_db_connection()
    if not conn:
        raise ConnectionError("Could not connect to database to save Garmin activity")

    act_id = garmin_act["activityId"]
    name = garmin_act.get("activityName") or "Workout"
    raw_type = garmin_act.get("activityType", {}).get("typeKey", "Workout")
    act_type = GARMIN_TYPE_MAP.get(raw_type.lower(), raw_type.capitalize())
    
    distance = float(garmin_act.get("distance") or 0.0)
    moving_duration = int(garmin_act.get("movingDuration") or garmin_act.get("duration") or 0)
    total_elapsed = int(garmin_act.get("elapsedDuration") or moving_duration)
    elevation_gain = float(garmin_act.get("elevationGain") or 0.0)

    start_str = garmin_act.get("startTimeLocal") or garmin_act.get("startTimeGMT")
    timestamp = parse_garmin_timestamp(start_str)

    user_id = str(garmin_act.get("ownerId") or os.getenv("STRAVA_USER_ID") or "user")

    # Fetch GPS polyline if available
    summary_polyline = None
    if garmin_act.get("hasPolyline") and client:
        try:
            details = client.get_activity_details(act_id)
            poly_points = details.get("geoPolylineDTO", {}).get("polyline", [])
            if poly_points:
                # Downsample points if large to keep polyline concise
                step = max(1, len(poly_points) // 250)
                sampled_coords = [(p["lat"], p["lon"]) for p in poly_points[::step] if "lat" in p and "lon" in p]
                summary_polyline = encode_coords_to_polyline(sampled_coords)
        except Exception as e:
            print(f"[GarminService] Note: Could not fetch route details for {act_id}: {e}")

    avg_hr = float(garmin_act.get("averageHR")) if garmin_act.get("averageHR") is not None else None
    max_hr = float(garmin_act.get("maxHR")) if garmin_act.get("maxHR") is not None else None

    text = format_activity_text(name, act_type, distance, elevation_gain, moving_duration)
    embedding = compute_embedding(text)

    try:
        with conn.cursor() as cur:
            # Check for existing activity with same timestamp & duration (to avoid duplicate from Strava archive)
            cur.execute("""
                SELECT activity_id FROM activities 
                WHERE timestamp = %s AND ABS(duration - %s) <= 15
            """, (timestamp, moving_duration))
            existing_row = cur.fetchone()

            target_id = existing_row[0] if existing_row else act_id

            cur.execute("""
                INSERT INTO activities (activity_id, user_id, activity_type, distance, duration, elevation_gain, elapsed_time, summary_polyline, timestamp, embedding, average_heartrate, max_heartrate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (activity_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    activity_type = EXCLUDED.activity_type,
                    distance = EXCLUDED.distance,
                    duration = EXCLUDED.duration,
                    elevation_gain = EXCLUDED.elevation_gain,
                    elapsed_time = EXCLUDED.elapsed_time,
                    summary_polyline = COALESCE(EXCLUDED.summary_polyline, activities.summary_polyline),
                    timestamp = EXCLUDED.timestamp,
                    embedding = EXCLUDED.embedding,
                    average_heartrate = COALESCE(EXCLUDED.average_heartrate, activities.average_heartrate),
                    max_heartrate = COALESCE(EXCLUDED.max_heartrate, activities.max_heartrate)
            """, (
                target_id,
                user_id,
                act_type,
                distance,
                moving_duration,
                elevation_gain,
                total_elapsed,
                summary_polyline,
                timestamp,
                embedding,
                avg_hr,
                max_hr
            ))
            conn.commit()

            # Invalidate cache for the affected year
            if timestamp and hasattr(timestamp, "year"):
                invalidate_cache_for_year(timestamp.year)
            else:
                invalidate_cache_for_year(datetime.now().year)

            return True
    finally:
        conn.close()


def get_sync_status_info():
    """Return status dictionary for sync endpoints."""
    global _last_sync_time, _is_syncing
    now = time.time()
    seconds_since = int(now - _last_sync_time) if _last_sync_time else None
    is_stale = (_last_sync_time is None) or (seconds_since > 900)  # 15 mins
    return {
        "provider": "garmin",
        "is_syncing": _is_syncing,
        "last_sync_time": _last_sync_time,
        "seconds_since_sync": seconds_since,
        "is_stale": is_stale
    }


def sync_garmin_incremental(limit=10, sync_wellness=True):
    """Fetch new workouts from Garmin that are newer than latest DB record."""
    global _last_sync_time, _is_syncing

    acquired = _sync_lock.acquire(blocking=False)
    if not acquired:
        return {
            "status": "in_progress",
            "message": "A Garmin sync is already running",
            "provider": "garmin",
            "synced_count": 0
        }

    _is_syncing = True
    try:
        client = get_garmin_client()

        conn = get_db_connection()
        latest_ts = None
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT MAX(timestamp) FROM activities")
                    row = cur.fetchone()
                    if row and row[0]:
                        latest_ts = row[0]
            finally:
                conn.close()

        print(f"[GarminService] Checking Garmin for activities (latest in DB: {latest_ts})...")
        garmin_activities = client.get_activities(0, min(limit, 20))
        if not garmin_activities:
            _last_sync_time = time.time()
            return {"status": "success", "synced_count": 0, "message": "No activities found in Garmin"}

        synced_count = 0
        synced_activities = []

        for act in garmin_activities:
            start_str = act.get("startTimeLocal") or act.get("startTimeGMT")
            act_ts = parse_garmin_timestamp(start_str)

            # If we have a latest timestamp, only ingest newer activities
            if latest_ts and act_ts <= latest_ts:
                continue

            try:
                save_garmin_activity_to_db(act, client=client)
                synced_count += 1
                synced_activities.append({
                    "id": act.get("activityId"),
                    "name": act.get("activityName"),
                    "type": act.get("activityType", {}).get("typeKey"),
                    "date": start_str
                })
                print(f"[GarminService] Synced: {act.get('activityName')} ({act.get('activityId')}) on {start_str}")
            except Exception as e:
                print(f"[GarminService] Error saving activity {act.get('activityId')}: {e}")

        # Offload daily wellness (steps, intensity minutes, active calories) to a daemon background thread
        # so the API call returns immediately without waiting ~20s for 7 day-by-day calls.
        if sync_wellness:
            def _async_wellness():
                try:
                    sync_garmin_wellness(days=7)
                except Exception as e:
                    print(f"[GarminService] Background wellness sync error: {e}")
            threading.Thread(target=_async_wellness, daemon=True).start()

        _last_sync_time = time.time()
        return {
            "status": "success",
            "provider": "garmin",
            "synced_count": synced_count,
            "activities": synced_activities,
            "last_sync_time": _last_sync_time
        }
    finally:
        _is_syncing = False
        _sync_lock.release()



def sync_garmin_wellness(days=14):
    """Fetch daily wellness summaries from Garmin and upsert into daily_wellness table."""
    client = get_garmin_client()
    conn = get_db_connection()
    if not conn:
        return {"status": "error", "message": "Database connection failed"}

    from datetime import timedelta
    today = datetime.utcnow().date()
    synced_days = 0

    try:
        with conn.cursor() as cur:
            for i in range(days):
                cal_date = today - timedelta(days=i)
                date_str = cal_date.strftime("%Y-%m-%d")
                try:
                    summary = client.get_user_summary(date_str)
                    steps = int(summary.get("totalSteps") or 0)
                    calories = float(summary.get("activeKilocalories") or 0.0)
                    mod_min = int(summary.get("moderateIntensityMinutes") or 0)
                    vig_min = int(summary.get("vigorousIntensityMinutes") or 0)
                    max_hr = int(summary.get("maxHeartRate") or 0)

                    cur.execute("""
                        INSERT INTO daily_wellness (calendar_date, total_steps, active_calories, moderate_intensity_minutes, vigorous_intensity_minutes, max_heart_rate, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (calendar_date) DO UPDATE SET
                            total_steps = EXCLUDED.total_steps,
                            active_calories = EXCLUDED.active_calories,
                            moderate_intensity_minutes = EXCLUDED.moderate_intensity_minutes,
                            vigorous_intensity_minutes = EXCLUDED.vigorous_intensity_minutes,
                            max_heart_rate = EXCLUDED.max_heart_rate,
                            updated_at = CURRENT_TIMESTAMP;
                    """, (cal_date, steps, calories, mod_min, vig_min, max_hr))
                    synced_days += 1
                except Exception as e:
                    print(f"[GarminService] Error fetching wellness for {date_str}: {e}")
            conn.commit()
        return {"status": "success", "synced_days": synced_days}
    finally:
        conn.close()
