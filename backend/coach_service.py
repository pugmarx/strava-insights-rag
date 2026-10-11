import os
import sys
import json
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
load_dotenv(os.path.join(project_root, ".env"))

from token_manager import get_db_connection
from llm_client import LLMClient
from route_service import get_staple_routes

# In-memory briefing cache
_BRIEFING_CACHE = None
_BRIEFING_CACHE_TIME = 0
BRIEFING_TTL_SECONDS = 600  # 10 minutes


def invalidate_coach_briefing_cache():
    """Clear in-memory and database coach briefing caches."""
    global _BRIEFING_CACHE, _BRIEFING_CACHE_TIME
    _BRIEFING_CACHE = None
    _BRIEFING_CACHE_TIME = 0
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM query_cache WHERE query_type = 'coach_briefing';")
                conn.commit()
        except Exception:
            pass
        finally:
            conn.close()


def get_coach_metrics():
    """Extract concrete 7-day and 30-day metrics, combining GPS rides and background movement."""
    conn = get_db_connection()
    if not conn:
        return {}

    try:
        with conn.cursor() as cur:
            ref_date = datetime.now().date()
            date_7d_ago = ref_date - timedelta(days=6)
            date_14d_ago = ref_date - timedelta(days=13)
            date_30d_ago = ref_date - timedelta(days=29)

            # 1. Consolidated window query (7-day, prev 7-day, 30-day in a single pass)
            cur.execute("""
                WITH window_bounds AS (
                    SELECT 
                        %s::date AS d7,
                        %s::date AS d14,
                        %s::date AS d30,
                        %s::date AS today
                )
                SELECT 
                    COUNT(*) FILTER (WHERE a.timestamp::date >= wb.d7) AS rides_7d,
                    COALESCE(SUM(a.distance) FILTER (WHERE a.timestamp::date >= wb.d7), 0) AS dist_7d,
                    COALESCE(SUM(a.duration) FILTER (WHERE a.timestamp::date >= wb.d7), 0) AS dur_7d,
                    AVG(a.average_heartrate) FILTER (WHERE a.timestamp::date >= wb.d7) AS avg_hr_7d,
                    MAX(a.max_heartrate) FILTER (WHERE a.timestamp::date >= wb.d7) AS max_hr_7d,
                    COUNT(*) FILTER (WHERE a.timestamp::date >= wb.d14 AND a.timestamp::date < wb.d7) AS prev_rides_7d,
                    COALESCE(SUM(a.distance) FILTER (WHERE a.timestamp::date >= wb.d14 AND a.timestamp::date < wb.d7), 0) AS prev_dist_7d,
                    COUNT(*) FILTER (WHERE a.timestamp::date >= wb.d30) AS rides_30d,
                    COALESCE(SUM(a.distance) FILTER (WHERE a.timestamp::date >= wb.d30), 0) AS dist_30d,
                    COALESCE(SUM(a.duration) FILTER (WHERE a.timestamp::date >= wb.d30), 0) AS dur_30d
                FROM activities a, window_bounds wb
                WHERE a.activity_type = 'Ride' AND a.timestamp::date >= wb.d30 AND a.timestamp::date <= wb.today;
            """, (date_7d_ago, date_14d_ago, date_30d_ago, ref_date))
            
            row = cur.fetchone()
            rides_7d = row[0] or 0
            km_7d = round(float(row[1]) / 1000.0, 1)
            dur_7d_sec = float(row[2] or 0)
            hours_7d = round(dur_7d_sec / 3600.0, 1)
            avg_speed_7d = round((km_7d / (dur_7d_sec / 3600.0)), 1) if dur_7d_sec > 0 else 0
            avg_hr_7d = round(float(row[3])) if row[3] else None
            max_hr_7d = round(float(row[4])) if row[4] else None

            prev_km_7d = round(float(row[6]) / 1000.0, 1)
            km_delta_7d = round(km_7d - prev_km_7d, 1)

            rides_30d = row[7] or 0
            km_30d = round(float(row[8]) / 1000.0, 1)
            hours_30d = round(float(row[9] or 0) / 3600.0, 1)

            # 2. Distinct Ride Dates in last 7 days
            cur.execute("""
                SELECT DISTINCT timestamp::date
                FROM activities
                WHERE activity_type = 'Ride' AND timestamp::date >= %s AND timestamp::date <= %s;
            """, (date_7d_ago, ref_date))
            ride_dates_7d = set(r[0] for r in cur.fetchall())

            # 3. Daily Wellness in last 7 days
            cur.execute("""
                SELECT calendar_date, (moderate_intensity_minutes + vigorous_intensity_minutes) as intensity_min, active_calories
                FROM daily_wellness
                WHERE calendar_date >= %s AND calendar_date <= %s;
            """, (date_7d_ago, ref_date))
            wellness_rows = cur.fetchall()

            cross_training_dates = set()
            total_intensity_min_7d = 0
            for w in wellness_rows:
                c_date, intensity_min, calories = w[0], w[1] or 0, w[2] or 0
                total_intensity_min_7d += intensity_min
                if (intensity_min >= 25 or calories >= 300) and (c_date not in ride_dates_7d):
                    cross_training_dates.add(c_date)

            active_days_count = len(ride_dates_7d | cross_training_dates)
            rest_days_count = max(0, 7 - active_days_count)

            # 4. Latest Ride summary & Heart Rate
            cur.execute("""
                SELECT activity_id, distance, duration, elevation_gain, timestamp, average_heartrate, max_heartrate
                FROM activities
                WHERE activity_type = 'Ride'
                ORDER BY timestamp DESC
                LIMIT 1;
            """)
            latest_row = cur.fetchone()
            latest_act = None
            days_since_ride = None
            if latest_row:
                l_id, l_dist, l_dur, l_elev, l_ts, l_avg_hr, l_max_hr = latest_row
                l_km = round(l_dist / 1000.0, 1)
                l_dur_min = round(l_dur / 60.0, 1)
                l_speed = round((l_km / (l_dur / 3600.0)), 1) if l_dur > 0 else 0
                days_since_ride = (ref_date - l_ts.date()).days if ref_date >= l_ts.date() else 0
                latest_act = {
                    "id": l_id,
                    "date": l_ts.strftime("%Y-%m-%d"),
                    "distance_km": l_km,
                    "duration_min": l_dur_min,
                    "speed_kmh": l_speed,
                    "elevation_m": round(float(l_elev or 0), 0),
                    "avg_heartrate": round(float(l_avg_hr)) if l_avg_hr else None,
                    "max_heartrate": round(float(l_max_hr)) if l_max_hr else None
                }

            # 5. Days since last long ride (> 20 km)
            cur.execute("""
                SELECT MAX(timestamp)
                FROM activities
                WHERE activity_type = 'Ride' AND distance >= 20000;
            """)
            long_row = cur.fetchone()
            days_since_long_ride = None
            if long_row and long_row[0]:
                long_dt = long_row[0].date()
                days_since_long_ride = (ref_date - long_dt).days

            return {
                "period": f"{date_7d_ago.strftime('%b %d')} - {ref_date.strftime('%b %d, %Y')}",
                "days_active": active_days_count,
                "rides_count_7d": rides_7d,
                "cross_training_days_7d": len(cross_training_dates),
                "rest_days_7d": rest_days_count,
                "total_intensity_min_7d": total_intensity_min_7d,
                "km_7d": km_7d,
                "hours_7d": hours_7d,
                "avg_speed_7d": avg_speed_7d,
                "avg_hr_7d": avg_hr_7d,
                "max_hr_7d": max_hr_7d,
                "km_delta_7d": f"{'+' if km_delta_7d >= 0 else ''}{km_delta_7d} km",
                "km_30d": km_30d,
                "rides_30d": rides_30d,
                "hours_30d": hours_30d,
                "days_since_ride": days_since_ride,
                "days_since_long_ride": days_since_long_ride,
                "latest_ride": latest_act
            }
    finally:
        conn.close()


def get_coach_briefing(force_refresh=False):
    """
    Generate or return cached Proactive Coach Briefing.
    Combines 7-day movement, ride consistency, and staple route podium context.
    """
    global _BRIEFING_CACHE, _BRIEFING_CACHE_TIME
    now = time.time()

    # 1. Check in-memory cache
    if not force_refresh and _BRIEFING_CACHE is not None and (now - _BRIEFING_CACHE_TIME) < BRIEFING_TTL_SECONDS:
        return _BRIEFING_CACHE

    # 2. Check DB query_cache
    if not force_refresh:
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT response, created_at
                        FROM query_cache
                        WHERE query_type = 'coach_briefing'
                        ORDER BY created_at DESC
                        LIMIT 1;
                    """)
                    row = cur.fetchone()
                    if row and row[0]:
                        try:
                            data = json.loads(row[0])
                            _BRIEFING_CACHE = data
                            _BRIEFING_CACHE_TIME = now
                            return data
                        except Exception:
                            pass
            finally:
                conn.close()

    # 3. Extract metrics
    metrics = get_coach_metrics()
    if not metrics:
        return {"error": "Could not extract metrics for coach briefing"}

    # 4. Check route context (did latest ride match any staple loop?)
    staples = get_staple_routes()
    route_context = ""
    latest_ride = metrics.get("latest_ride") or {}
    if staples and latest_ride:
        latest_id = latest_ride.get("id")
        for s in staples:
            if s.get("latest_attempt", {}).get("activity_id") == latest_id:
                lat = s["latest_attempt"]
                delta_str = lat.get("delta_vs_recent", "")
                status_str = lat.get("form_status", "")
                route_context = f"The latest ride on {latest_ride.get('date')} was on the '{s['name']}' ({s['distance_km']} km). Speed: {latest_ride.get('speed_kmh')} km/h ({delta_str} vs recent baseline; {status_str})."
                break

    # 5. Build prompt for Groq LLM with physiological HR context
    hr_context = ""
    latest_hr = latest_ride.get("avg_heartrate")
    latest_max_hr = latest_ride.get("max_heartrate")
    if latest_hr:
        hr_context = f"- Heart Rate Telemetry: Latest workout average HR was {latest_hr} bpm (peak {latest_max_hr} bpm). 7-day average riding HR: {metrics.get('avg_hr_7d') or latest_hr} bpm."
    else:
        hr_context = "- Heart Rate Telemetry: Not recorded on latest device (focus on speed, cadence, and duration metrics)."

    prompt = f"""
You are a direct, pragmatic cycling coach analyzing the athlete's current training status.
Write a 3-bullet briefing directly to the athlete based ONLY on these factual metrics.
DO NOT talk about past years, memoirs, or heydays. Focus entirely on present momentum, recent workouts, cardiovascular intensity, and next focus.

Metrics:
- 7-Day Consistency: {metrics['days_active']} of 7 days active ({metrics['rides_count_7d']} rides, {metrics['cross_training_days_7d']} cross-training/movement days like ping-pong/walking, {metrics['rest_days_7d']} rest days).
- 7-Day Ride Volume: {metrics['km_7d']} km in {metrics['hours_7d']} hours (Average speed: {metrics['avg_speed_7d']} km/h, Week-over-Week delta: {metrics['km_delta_7d']}).
- Total Intensity Minutes this week: {metrics['total_intensity_min_7d']} mins.
- 30-Day Volume: {metrics['km_30d']} km across {metrics['rides_30d']} rides.
- Recency: Last ride was {metrics['days_since_ride']} days ago ({latest_ride.get('distance_km')} km at {latest_ride.get('speed_kmh')} km/h).
- Endurance Recency: Last ride over 20km was {metrics['days_since_long_ride']} days ago.
- Route Context: {route_context or 'Latest workout completed standard training loop.'}
{hr_context}

Format rules:
Output EXACTLY 3 bold bullet points:
1. **Current Momentum**: Summarize the 7-day consistency and volume cleanly. Give credit for active days (rides + unrecorded sports like ping-pong or walking).
2. **Recent Workout & Cardiovascular Response**: Discuss the latest ride pace, speed delta, and heart rate effort (aerobic base vs threshold stress) if HR was recorded.
3. **Actionable Focus**: Give a concrete training recommendation for the next 48-72 hours (e.g. endurance cadence, recovery spin, or tempo).

Keep the entire output under 130 words. No intro text, no outro text. Start immediately with the bullets.
"""

    llm = LLMClient()
    briefing_text = llm.generate(prompt)

    result = {
        "status": "success",
        "generated_at": datetime.utcnow().isoformat(),
        "metrics": metrics,
        "briefing_markdown": briefing_text
    }

    # 6. Cache result
    _BRIEFING_CACHE = result
    _BRIEFING_CACHE_TIME = now

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM query_cache WHERE query_type = 'coach_briefing';")
                # fastembed dummy embedding for schema compatibility
                cur.execute("""
                    INSERT INTO query_cache (query_text, query_type, target_year, is_historical, embedding, response, created_at)
                    VALUES ('coach_briefing_latest', 'coach_briefing', NULL, FALSE, array_fill(0.0, ARRAY[384])::vector, %s, CURRENT_TIMESTAMP);
                """, (json.dumps(result),))
                conn.commit()
        except Exception as e:
            print(f"[CoachService] Cache write note: {e}")
        finally:
            conn.close()

    return result
