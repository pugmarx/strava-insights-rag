"""
Recent Activity Service
Provides fast chronological workout telemetry, rolling form medians,
and cardiovascular efficiency metrics without requiring route clustering.
"""

import os
import statistics
from datetime import datetime
from dotenv import load_dotenv

backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
load_dotenv(os.path.join(project_root, ".env"))

from token_manager import get_db_connection


def format_duration(seconds):
    """Convert seconds to human readable string (e.g. '56m 48s' or '1h 12m')."""
    if not seconds:
        return "0m"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {secs}s" if secs > 0 else f"{minutes}m"


def get_recent_rides(limit=20):
    """
    Fetch the last N cycling activities in chronological order.
    Computes pace, heart rate telemetry, and rolling performance baselines.
    """
    limit = max(1, min(limit, 50))
    conn = get_db_connection()
    if not conn:
        return {
            "latest_activity": None,
            "recent_activities": [],
            "medians": {}
        }

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT activity_id, distance, duration, elevation_gain, timestamp, average_heartrate, max_heartrate
                FROM activities
                WHERE activity_type = 'Ride' AND distance > 1000
                ORDER BY timestamp DESC
                LIMIT %s;
            """, (limit,))
            rows = cur.fetchall()

        if not rows:
            return {
                "latest_activity": None,
                "recent_activities": [],
                "medians": {}
            }

        rides = []
        for r in rows:
            act_id, dist, dur, elev, ts, avg_hr, max_hr = r
            dist_km = round(float(dist or 0) / 1000.0, 2)
            dur_sec = int(dur or 0)
            dur_min = round(dur_sec / 60.0, 1)
            speed_kmh = round((dist_km / (dur_sec / 3600.0)), 1) if dur_sec > 0 else 0.0
            elev_m = round(float(elev or 0), 0)
            avg_hr_val = round(float(avg_hr)) if avg_hr else None
            max_hr_val = round(float(max_hr)) if max_hr else None

            # Aerobic efficiency: speed_kmh per 100 bpm (e.g. 16.5 / 146 * 100 = 11.3)
            efficiency_ratio = round((speed_kmh / avg_hr_val) * 100, 1) if avg_hr_val and avg_hr_val > 0 else None

            rides.append({
                "activity_id": act_id,
                "date": ts.strftime("%b %d, %Y") if ts else "Unknown",
                "time": ts.strftime("%H:%M") if ts else "",
                "timestamp": ts.isoformat() if ts else None,
                "distance_km": dist_km,
                "duration_sec": dur_sec,
                "duration_min": dur_min,
                "duration_str": format_duration(dur_sec),
                "speed_kmh": speed_kmh,
                "elevation_m": elev_m,
                "avg_heartrate": avg_hr_val,
                "max_heartrate": max_hr_val,
                "efficiency_ratio": efficiency_ratio
            })

        latest = rides[0] if rides else None

        # Compute medians over the returned set
        speeds = [x["speed_kmh"] for x in rides if x["speed_kmh"] > 0]
        hrs = [x["avg_heartrate"] for x in rides if x["avg_heartrate"] is not None]
        dists = [x["distance_km"] for x in rides if x["distance_km"] > 0]

        median_speed = round(statistics.median(speeds), 1) if speeds else 0.0
        median_hr = round(statistics.median(hrs)) if hrs else None
        median_dist = round(statistics.median(dists), 1) if dists else 0.0

        # Form delta for latest ride vs rolling median
        latest_speed_delta = None
        if latest and median_speed > 0:
            diff = round(latest["speed_kmh"] - median_speed, 1)
            latest_speed_delta = f"{'+' if diff >= 0 else ''}{diff} km/h"

        return {
            "latest_activity": latest,
            "recent_activities": rides,  # sorted from newest to oldest
            "medians": {
                "speed_kmh": median_speed,
                "avg_heartrate": median_hr,
                "distance_km": median_dist,
                "latest_speed_delta": latest_speed_delta,
                "count": len(rides)
            }
        }
    finally:
        conn.close()
