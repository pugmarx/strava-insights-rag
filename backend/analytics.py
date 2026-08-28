import os
import sys
from datetime import datetime
import psycopg2
import numpy as np

# Ensure backend directory is in path
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, ".env"))
load_dotenv()

from token_manager import get_db_connection
from cache_manager import get_cached_analytics, set_cached_analytics


def get_breakthrough_analytics(activity_filter=None):
    """
    Computes statistical clusters, climbing metrics, and breakthrough classifications
    for all activities stored in the database with in-memory TTL caching.
    """
    cached_data = get_cached_analytics(activity_filter)
    if cached_data is not None:
        return cached_data

    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed", "activities": []}

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT activity_id, activity_type, distance, duration,
                       COALESCE(elevation_gain, 0) as elevation_gain, timestamp
                FROM activities
                WHERE duration > 60 AND distance > 100
                ORDER BY timestamp DESC;
            """)
            rows = cur.fetchall()

        if not rows:
            return {"activities": [], "summary": {}}

        # Parse rows into structured dictionaries
        raw_activities = []
        for row in rows:
            act_id, act_type, dist, dur, elev, ts = row
            dist_km = (dist / 1000.0) if dist else 0.0
            dur_sec = dur if dur else 0
            dur_hours = dur_sec / 3600.0
            dur_min = dur_sec / 60.0
            speed_kmh = (dist_km / dur_hours) if dur_hours > 0 else 0.0
            pace_min_km = (dur_min / dist_km) if dist_km > 0 else 0.0
            elevation_m = float(elev or 0.0)
            vam = (elevation_m / dur_hours) if dur_hours > 0 else 0.0
            gradient_pct = (elevation_m / dist * 100.0) if dist and dist > 0 else 0.0

            # Duration formatting
            hours = dur_sec // 3600
            mins = (dur_sec % 3600) // 60
            dur_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
            date_str = ts.strftime('%Y-%m-%d') if ts else 'Unknown'

            raw_activities.append({
                "id": act_id,
                "type": act_type,
                "date": date_str,
                "timestamp": ts.isoformat() if ts else None,
                "distance_km": round(dist_km, 2),
                "duration_min": round(dur_min, 1),
                "duration_str": dur_str,
                "speed_kmh": round(speed_kmh, 1),
                "pace_min_km": round(pace_min_km, 2),
                "elevation_m": round(elevation_m, 0),
                "vam": round(vam, 1),
                "gradient_pct": round(gradient_pct, 1)
            })

        # Group by activity type for statistical analysis
        by_type = {}
        for act in raw_activities:
            t = act["type"]
            by_type.setdefault(t, []).append(act)

        # Statistical Thresholds per activity type
        processed_activities = []
        counts = {
            "total": len(raw_activities),
            "climbing_breakthroughs": 0,
            "speed_breakthroughs": 0,
            "ultra_endurance": 0,
            "recovery": 0,
            "standard": 0
        }

        for act_type, items in by_type.items():
            if len(items) < 5:
                # Not enough points for IQR, mark standard
                for item in items:
                    item["category"] = "Standard"
                    item["color"] = "#64748b"
                    processed_activities.append(item)
                    counts["standard"] += 1
                continue

            speeds = np.array([x["speed_kmh"] for x in items])
            elevs = np.array([x["elevation_m"] for x in items])
            durs = np.array([x["duration_min"] for x in items])
            dists = np.array([x["distance_km"] for x in items])

            # Speed statistics
            q25_speed, q75_speed = np.percentile(speeds, [25, 75])
            iqr_speed = q75_speed - q25_speed
            median_dist = np.median(dists)

            # Elevation statistics
            q25_elev, q75_elev = np.percentile(elevs, [25, 75])
            iqr_elev = q75_elev - q25_elev
            p90_elev = np.percentile(elevs, 90)

            # Duration statistics
            q25_dur, q75_dur = np.percentile(durs, [25, 75])
            iqr_dur = q75_dur - q25_dur

            for item in items:
                # 1. Climbing Breakthrough: High elevation & high gradient
                if item["elevation_m"] >= max(p90_elev, 250) and item["elevation_m"] >= (q75_elev + 1.0 * iqr_elev):
                    item["category"] = "Climbing Breakthrough"
                    item["badge"] = "⛰️ Mountain King"
                    item["color"] = "#f59e0b"  # Glowing Amber
                    counts["climbing_breakthroughs"] += 1

                # 2. Speed Breakthrough: High speed on significant distance
                elif item["speed_kmh"] >= (q75_speed + 1.2 * iqr_speed) and item["distance_km"] >= (median_dist * 0.7):
                    item["category"] = "Speed Breakthrough"
                    item["badge"] = "⚡ Speed Outlier"
                    item["color"] = "#10b981"  # Emerald Green
                    counts["speed_breakthroughs"] += 1

                # 3. Ultra-Endurance: Statistical duration ceiling
                elif item["duration_min"] >= (q75_dur + 1.5 * iqr_dur) or item["duration_min"] >= 240:
                    item["category"] = "Ultra-Endurance"
                    item["badge"] = "⏱️ Epic Endurance"
                    item["color"] = "#3b82f6"  # Blue
                    counts["ultra_endurance"] += 1

                # 4. Recovery / Fatigue Outlier
                elif item["speed_kmh"] <= max(1.0, q25_speed - 1.2 * iqr_speed) and item["elevation_m"] < 150:
                    item["category"] = "Recovery / Fatigue"
                    item["badge"] = "💤 Recovery Day"
                    item["color"] = "#94a3b8"  # Slate Muted
                    counts["recovery"] += 1

                # 5. Standard Baseline
                else:
                    item["category"] = "Standard Training"
                    item["badge"] = "🟢 Standard"
                    item["color"] = "#475569"  # Dark Slate
                    counts["standard"] += 1

                processed_activities.append(item)

        # Sort chronologically by date descending
        processed_activities.sort(key=lambda x: x["date"], reverse=True)

        result = {
            "summary": counts,
            "activities": processed_activities
        }
        set_cached_analytics(activity_filter, result)
        return result

    except Exception as e:
        print(f"[Analytics] Error generating breakthrough analytics: {e}")
        return {"error": str(e), "activities": []}
    finally:
        conn.close()
