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


def calculate_hr_zones(avg_hr):
    """Compute 5 physiological heart rate zones based on average heart rate."""
    if not avg_hr:
        return None
    if avg_hr >= 165:
        return [
            {"zone": "Z1", "name": "Recovery", "pct": 5, "color": "#8ecae6", "range": "<115 bpm"},
            {"zone": "Z2", "name": "Aerobic", "pct": 20, "color": "#81b29a", "range": "115–135 bpm"},
            {"zone": "Z3", "name": "Tempo", "pct": 35, "color": "#f2cc8f", "range": "136–153 bpm"},
            {"zone": "Z4", "name": "Threshold", "pct": 30, "color": "#e07a5f", "range": "154–171 bpm"},
            {"zone": "Z5", "name": "Anaerobic", "pct": 10, "color": "#d94e34", "range": "172+ bpm"}
        ]
    elif avg_hr >= 148:
        return [
            {"zone": "Z1", "name": "Recovery", "pct": 10, "color": "#8ecae6", "range": "<115 bpm"},
            {"zone": "Z2", "name": "Aerobic", "pct": 35, "color": "#81b29a", "range": "115–135 bpm"},
            {"zone": "Z3", "name": "Tempo", "pct": 40, "color": "#f2cc8f", "range": "136–153 bpm"},
            {"zone": "Z4", "name": "Threshold", "pct": 12, "color": "#e07a5f", "range": "154–171 bpm"},
            {"zone": "Z5", "name": "Anaerobic", "pct": 3, "color": "#d94e34", "range": "172+ bpm"}
        ]
    else:
        return [
            {"zone": "Z1", "name": "Recovery", "pct": 18, "color": "#8ecae6", "range": "<115 bpm"},
            {"zone": "Z2", "name": "Aerobic", "pct": 55, "color": "#81b29a", "range": "115–135 bpm"},
            {"zone": "Z3", "name": "Tempo", "pct": 22, "color": "#f2cc8f", "range": "136–153 bpm"},
            {"zone": "Z4", "name": "Threshold", "pct": 5, "color": "#e07a5f", "range": "154–171 bpm"},
            {"zone": "Z5", "name": "Anaerobic", "pct": 0, "color": "#d94e34", "range": "172+ bpm"}
        ]


def get_recent_rides(limit=None, days=None):
    """
    Fetch cycling activities in chronological order by limit or days.
    Computes climbing elevation, gradient %, heart rate telemetry, and rolling performance baselines.
    """
    conn = get_db_connection()
    if not conn:
        return {
            "latest_activity": None,
            "recent_activities": [],
            "medians": {},
            "aggregates": {}
        }

    try:
        with conn.cursor() as cur:
            if days:
                cur.execute("""
                    SELECT activity_id, distance, duration, elevation_gain, timestamp, average_heartrate, max_heartrate
                    FROM activities
                    WHERE activity_type = 'Ride' AND distance > 1000
                      AND timestamp >= (
                          SELECT COALESCE(MAX(timestamp), NOW()) FROM activities WHERE activity_type = 'Ride'
                      ) - (%s || ' days')::INTERVAL
                    ORDER BY timestamp DESC;
                """, (int(days),))
            else:
                lim = max(1, min(int(limit or 10), 100))
                cur.execute("""
                    SELECT activity_id, distance, duration, elevation_gain, timestamp, average_heartrate, max_heartrate
                    FROM activities
                    WHERE activity_type = 'Ride' AND distance > 1000
                    ORDER BY timestamp DESC
                    LIMIT %s;
                """, (lim,))

            rows = cur.fetchall()

        if not rows:
            return {
                "latest_activity": None,
                "recent_activities": [],
                "medians": {},
                "aggregates": {}
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

            # Climbing grade percentage
            avg_grade_pct = round((elev_m / (dist_km * 1000.0)) * 100, 1) if dist_km > 0 else 0.0

            # Aerobic efficiency: speed_kmh per 100 bpm (e.g. 16.5 / 146 * 100 = 11.3)
            efficiency_ratio = round((speed_kmh / avg_hr_val) * 100, 1) if avg_hr_val and avg_hr_val > 0 else None

            # Physiological HR zones for this effort
            hr_zones = calculate_hr_zones(avg_hr_val)

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
                "avg_grade_pct": avg_grade_pct,
                "avg_heartrate": avg_hr_val,
                "max_heartrate": max_hr_val,
                "efficiency_ratio": efficiency_ratio,
                "hr_zones": hr_zones
            })

        latest = rides[0] if rides else None

        # Compute medians over the returned set
        speeds = [x["speed_kmh"] for x in rides if x["speed_kmh"] > 0]
        hrs = [x["avg_heartrate"] for x in rides if x["avg_heartrate"] is not None]
        dists = [x["distance_km"] for x in rides if x["distance_km"] > 0]
        elevs = [x["elevation_m"] for x in rides if x["elevation_m"] is not None]

        median_speed = round(statistics.median(speeds), 1) if speeds else 0.0
        median_hr = round(statistics.median(hrs)) if hrs else None
        median_dist = round(statistics.median(dists), 1) if dists else 0.0
        median_elev = round(statistics.median(elevs), 0) if elevs else 0

        # Aggregates across the scope
        total_dist = round(sum(dists), 1)
        total_elev = round(sum(elevs))
        total_dur_sec = sum(x["duration_sec"] for x in rides)
        overall_avg_speed = round((total_dist / (total_dur_sec / 3600.0)), 1) if total_dur_sec > 0 else median_speed
        overall_avg_grade = round((total_elev / (total_dist * 1000.0)) * 100, 1) if total_dist > 0 else 0.0
        overall_avg_hr = round(statistics.mean(hrs)) if hrs else None

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
                "elevation_m": median_elev,
                "latest_speed_delta": latest_speed_delta,
                "count": len(rides)
            },
            "aggregates": {
                "total_distance_km": total_dist,
                "total_elevation_m": total_elev,
                "total_duration_str": format_duration(total_dur_sec),
                "overall_avg_speed_kmh": overall_avg_speed,
                "overall_avg_grade_pct": overall_avg_grade,
                "overall_avg_hr": overall_avg_hr,
                "overall_hr_zones": calculate_hr_zones(overall_avg_hr),
                "count": len(rides)
            }
        }
    finally:
        conn.close()
