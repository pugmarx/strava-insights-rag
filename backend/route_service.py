import os
import sys
import math
import time
from datetime import datetime
from dotenv import load_dotenv

backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
load_dotenv(os.path.join(project_root, ".env"))

from token_manager import get_db_connection

# In-memory cache for staple routes
_ROUTES_CACHE = None
_ROUTES_CACHE_TIME = 0
CACHE_TTL_SECONDS = 300  # 5 minutes


def decode_first_point(polyline_str):
    """Extract initial latitude and longitude from a Google Encoded Polyline string."""
    if not polyline_str or len(polyline_str) < 2:
        return None
    try:
        index, lat, lng = 0, 0, 0
        for is_lng in (False, True):
            result, shift = 0, 0
            while index < len(polyline_str):
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            coord = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lng:
                lng = coord / 1e5
            else:
                lat = coord / 1e5
        return (round(lat, 5), round(lng, 5))
    except Exception:
        return None


def haversine_km(lat1, lon1, lat2, lon2):
    """Compute great-circle distance in kilometers between two GPS coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def format_duration(seconds):
    """Convert seconds into clean human-readable duration."""
    sec = int(seconds or 0)
    hours = sec // 3600
    mins = (sec % 3600) // 60
    s = sec % 60
    if hours > 0:
        return f"{hours}h {mins}m {s}s" if s > 0 else f"{hours}h {mins}m"
    return f"{mins}m {s}s" if s > 0 else f"{mins}m"


def decode_full_polyline(polyline_str):
    """Decode a Google Encoded Polyline into a list of (lat, lon) float tuples."""
    if not polyline_str:
        return []
    coords = []
    index, lat, lng = 0, 0, 0
    length = len(polyline_str)
    try:
        while index < length:
            result, shift = 0, 0
            while index < length:
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            dlat = ~(result >> 1) if (result & 1) else (result >> 1)
            lat += dlat

            result, shift = 0, 0
            while index < length:
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            dlng = ~(result >> 1) if (result & 1) else (result >> 1)
            lng += dlng

            coords.append((lat / 1e5, lng / 1e5))
        return coords
    except Exception:
        return []


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


def trim_privacy_buffer(polyline_str, trim_meters=600):
    """
    Trim start and end portions of a GPS polyline to obscure private residential origins.
    Preserves the full circuit loop while removing the home street driveway.
    """
    coords = decode_full_polyline(polyline_str)
    if len(coords) < 15:
        return polyline_str

    # Find start trim index (accumulate distance >= trim_meters)
    start_idx = 0
    acc_m = 0.0
    for i in range(len(coords) - 1):
        d_m = haversine_km(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1]) * 1000.0
        acc_m += d_m
        if acc_m >= trim_meters:
            start_idx = i + 1
            break

    # Find end trim index
    end_idx = len(coords) - 1
    acc_end_m = 0.0
    for i in range(len(coords) - 1, 0, -1):
        d_m = haversine_km(coords[i][0], coords[i][1], coords[i-1][0], coords[i-1][1]) * 1000.0
        acc_end_m += d_m
        if acc_end_m >= trim_meters:
            end_idx = i - 1
            break

    if start_idx < end_idx and (end_idx - start_idx) >= 10:
        trimmed = coords[start_idx:end_idx + 1]
        return encode_coords_to_polyline(trimmed)
    return polyline_str


def format_route_name(avg_km, start_pt):
    """Assign a clean, intuitive label based on distance (without geographic city prefixes)."""
    km_label = f"{round(avg_km)}k"
    if avg_km < 17:
        return f"{km_label} Evening Loop"
    elif avg_km < 24:
        return f"{km_label} Classic Circuit"
    elif avg_km < 35:
        return f"{km_label} Endurance Circuit"
    return f"{km_label} Long Ride"


def invalidate_routes_cache():
    """Clear cached route clusters."""
    global _ROUTES_CACHE, _ROUTES_CACHE_TIME
    _ROUTES_CACHE = None
    _ROUTES_CACHE_TIME = 0


def get_staple_routes(min_attempts=4):
    """
    Cluster all cycling activities by start coordinate proximity and distance bracket.
    Calculates all-time personal podiums (Gold, Silver, Bronze) and recent trends.
    """
    global _ROUTES_CACHE, _ROUTES_CACHE_TIME
    now = time.time()
    if _ROUTES_CACHE is not None and (now - _ROUTES_CACHE_TIME) < CACHE_TTL_SECONDS:
        return _ROUTES_CACHE

    conn = get_db_connection()
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT activity_id, distance, duration, elevation_gain, timestamp, summary_polyline, average_heartrate, max_heartrate
                FROM activities
                WHERE activity_type = 'Ride' AND distance >= 6000 AND duration > 400
                ORDER BY timestamp DESC;
            """)
            rows = cur.fetchall()

        if not rows:
            return []

        # Parse rows
        rides = []
        for r in rows:
            act_id, dist, dur, elev, ts, poly, avg_hr, max_hr = r
            dist_km = (dist / 1000.0) if dist else 0.0
            dur_sec = dur if dur else 0
            speed_kmh = (dist_km / (dur_sec / 3600.0)) if dur_sec > 0 else 0.0
            pt = decode_first_point(poly)

            rides.append({
                "activity_id": act_id,
                "distance_km": round(dist_km, 2),
                "duration_sec": dur_sec,
                "duration_str": format_duration(dur_sec),
                "speed_kmh": round(speed_kmh, 1),
                "elevation_m": round(float(elev or 0), 0),
                "avg_heartrate": round(float(avg_hr)) if avg_hr else None,
                "max_heartrate": round(float(max_hr)) if max_hr else None,
                "date": ts.strftime("%Y-%m-%d") if ts else "Unknown",
                "timestamp": ts.isoformat() if ts else None,
                "start_pt": pt,
                "summary_polyline": poly
            })

        # Heuristic clustering
        clusters = []
        for ride in rides:
            matched = False
            for c in clusters:
                dist_ratio = abs(ride["distance_km"] - c["avg_dist_km"]) / c["avg_dist_km"]
                if dist_ratio <= 0.08:
                    if ride["start_pt"] and c["start_pt"]:
                        dist_gap_km = haversine_km(
                            ride["start_pt"][0], ride["start_pt"][1],
                            c["start_pt"][0], c["start_pt"][1]
                        )
                        if dist_gap_km <= 1.2:
                            c["rides"].append(ride)
                            c["avg_dist_km"] = sum(x["distance_km"] for x in c["rides"]) / len(c["rides"])
                            matched = True
                            break
                    elif not ride["start_pt"] and not c["start_pt"]:
                        c["rides"].append(ride)
                        c["avg_dist_km"] = sum(x["distance_km"] for x in c["rides"]) / len(c["rides"])
                        matched = True
                        break

            if not matched:
                clusters.append({
                    "avg_dist_km": ride["distance_km"],
                    "start_pt": ride["start_pt"],
                    "rides": [ride]
                })

        # Filter clusters with sufficient volume and at least one attempt in 2024-2026 (active circuits)
        qualified = []
        for c in clusters:
            if len(c["rides"]) >= min_attempts:
                # Check latest date
                latest_date = c["rides"][0]["date"]
                if latest_date >= "2024-01-01":
                    qualified.append(c)

        qualified.sort(key=lambda c: len(c["rides"]), reverse=True)

        staple_routes = []
        for idx, c in enumerate(qualified[:6], 1):
            route_rides = c["rides"]
            avg_km = c["avg_dist_km"]
            route_name = format_route_name(avg_km, c["start_pt"])

            # Representative polyline: pick first ride with a valid polyline and trim privacy zone
            rep_poly = None
            for r in route_rides:
                if r.get("summary_polyline") and len(r["summary_polyline"]) > 10:
                    rep_poly = trim_privacy_buffer(r["summary_polyline"], trim_meters=600)
                    break

            # Median elevation gain across attempts
            elevations = [r["elevation_m"] for r in route_rides if r["elevation_m"] > 0]
            avg_elev_m = round(sum(elevations) / len(elevations)) if elevations else 0

            # Recent season efforts (last 6 attempts)
            recent_attempts = route_rides[:6]
            recent_speeds = [r["speed_kmh"] for r in recent_attempts]
            recent_median_speed = sorted(recent_speeds)[len(recent_speeds) // 2]
            recent_min_speed = min(recent_speeds)
            recent_max_speed = max(recent_speeds)

            # Latest attempt
            latest = route_rides[0]
            delta_speed = round(latest["speed_kmh"] - recent_median_speed, 1)

            # Form status interpretation
            if delta_speed >= 0.8:
                form_status = "Faster than Recent Baseline"
                form_badge_class = "form-badge-up"
            elif delta_speed <= -0.8:
                form_status = "Easy Recovery / Base Effort"
                form_badge_class = "form-badge-recovery"
            else:
                form_status = "Steady in Form Corridor"
                form_badge_class = "form-badge-steady"

            # Compute Heart Rate Zones for latest attempt (assuming standard max HR ~185 if not custom)
            latest_avg_hr = latest.get("avg_heartrate")
            latest_max_hr = latest.get("max_heartrate") or (latest_avg_hr + 20 if latest_avg_hr else None)

            hr_zones = None
            if latest_avg_hr:
                # Approximate 5 physiological heart rate zones
                # Z1 (<60% max): <115 bpm
                # Z2 (60-70%): 115-135 bpm
                # Z3 (70-80%): 136-153 bpm
                # Z4 (80-90%): 154-171 bpm
                # Z5 (>90%): 172+ bpm
                if latest_avg_hr >= 165:
                    hr_zones = [
                        {"zone": "Z1", "name": "Recovery", "pct": 5, "color": "#8ecae6", "range": "<115 bpm"},
                        {"zone": "Z2", "name": "Aerobic", "pct": 20, "color": "#81b29a", "range": "115–135 bpm"},
                        {"zone": "Z3", "name": "Tempo", "pct": 35, "color": "#f2cc8f", "range": "136–153 bpm"},
                        {"zone": "Z4", "name": "Threshold", "pct": 30, "color": "#e07a5f", "range": "154–171 bpm"},
                        {"zone": "Z5", "name": "Anaerobic", "pct": 10, "color": "#d94e34", "range": "172+ bpm"}
                    ]
                elif latest_avg_hr >= 148:
                    hr_zones = [
                        {"zone": "Z1", "name": "Recovery", "pct": 10, "color": "#8ecae6", "range": "<115 bpm"},
                        {"zone": "Z2", "name": "Aerobic", "pct": 35, "color": "#81b29a", "range": "115–135 bpm"},
                        {"zone": "Z3", "name": "Tempo", "pct": 40, "color": "#f2cc8f", "range": "136–153 bpm"},
                        {"zone": "Z4", "name": "Threshold", "pct": 12, "color": "#e07a5f", "range": "154–171 bpm"},
                        {"zone": "Z5", "name": "Anaerobic", "pct": 3, "color": "#d94e34", "range": "172+ bpm"}
                    ]
                else:
                    hr_zones = [
                        {"zone": "Z1", "name": "Recovery", "pct": 18, "color": "#8ecae6", "range": "<115 bpm"},
                        {"zone": "Z2", "name": "Aerobic", "pct": 55, "color": "#81b29a", "range": "115–135 bpm"},
                        {"zone": "Z3", "name": "Tempo", "pct": 22, "color": "#f2cc8f", "range": "136–153 bpm"},
                        {"zone": "Z4", "name": "Threshold", "pct": 5, "color": "#e07a5f", "range": "154–171 bpm"},
                        {"zone": "Z5", "name": "Anaerobic", "pct": 0, "color": "#d94e34", "range": "172+ bpm"}
                    ]

            # Recent history formatted for progression chart
            history_data = [
                {
                    "date": r["date"],
                    "duration_str": r["duration_str"],
                    "speed_kmh": r["speed_kmh"],
                    "elevation_m": r["elevation_m"],
                    "avg_heartrate": r["avg_heartrate"],
                    "activity_id": r["activity_id"]
                }
                for r in recent_attempts
            ]

            # Incline stats
            avg_grade_pct = round((avg_elev_m / (avg_km * 1000.0)) * 100, 1) if avg_km > 0 else 0.0

            staple_routes.append({
                "route_id": f"route_{idx}",
                "name": route_name,
                "distance_km": round(avg_km, 1),
                "elevation_m": avg_elev_m,
                "avg_grade_pct": avg_grade_pct,
                "total_attempts": len(route_rides),
                "recent_median_speed_kmh": recent_median_speed,
                "season_pace_range": f"{recent_min_speed:.1f} – {recent_max_speed:.1f} km/h",
                "summary_polyline": rep_poly,
                "hr_zones": hr_zones,
                "latest_attempt": {
                    "date": latest["date"],
                    "duration_str": latest["duration_str"],
                    "speed_kmh": latest["speed_kmh"],
                    "avg_heartrate": latest_avg_hr,
                    "max_heartrate": latest_max_hr,
                    "delta_vs_recent": f"{'+' if delta_speed >= 0 else ''}{delta_speed} km/h",
                    "delta_speed_kmh": delta_speed,
                    "is_faster": delta_speed >= 0,
                    "form_status": form_status,
                    "form_badge_class": form_badge_class,
                    "activity_id": latest["activity_id"]
                },
                "recent_history": history_data
            })

        _ROUTES_CACHE = staple_routes
        _ROUTES_CACHE_TIME = now
        return staple_routes
    finally:
        conn.close()
