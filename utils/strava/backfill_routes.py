#!/usr/bin/env python3
"""
Fast Backfill Routes Utility
Backfills `summary_polyline` from `activities.json` into Supabase PostgreSQL activities table.
"""

import os
import sys
import json
import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(project_root, ".env"))
load_dotenv()

sys.path.insert(0, os.path.join(project_root, "backend"))
from token_manager import get_db_connection, get_valid_access_token


def ensure_schema(conn):
    """Ensure summary_polyline column and activity_streams table exist."""
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE activities ADD COLUMN IF NOT EXISTS summary_polyline TEXT;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_streams (
                activity_id BIGINT PRIMARY KEY,
                streams_json JSONB NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS activity_streams_created_at_idx ON activity_streams (created_at);
            ALTER TABLE IF EXISTS activity_streams ENABLE ROW LEVEL SECURITY;
        """)
        conn.commit()


def backfill_polylines_from_json(conn, json_path):
    """Bulk update summary_polyline from activities.json."""
    if not os.path.exists(json_path):
        print(f"[Backfill] File not found: {json_path}")
        return 0

    with open(json_path, "r", encoding="utf-8") as f:
        activities = json.load(f)

    if not isinstance(activities, list):
        print(f"[Backfill] Invalid JSON structure in {json_path}")
        return 0

    records_to_update = []
    for act in activities:
        act_id = act.get("id")
        map_obj = act.get("map") or {}
        polyline = map_obj.get("summary_polyline") if isinstance(map_obj, dict) else None
        if act_id and polyline:
            records_to_update.append((polyline, act_id))

    print(f"[Backfill] Extracted {len(records_to_update)} route polylines from {json_path}.")
    if not records_to_update:
        return 0

    query = """
        UPDATE activities
        SET summary_polyline = %s
        WHERE activity_id = %s;
    """

    with conn.cursor() as cur:
        execute_batch(cur, query, records_to_update, page_size=200)
        conn.commit()

    print(f"[Backfill] Successfully backfilled {len(records_to_update)} polylines in Supabase.")
    return len(records_to_update)


def backfill_missing_via_api(conn):
    """Fetch summary_polyline for any outdoor activities in DB missing polylines."""
    import requests
    with conn.cursor() as cur:
        cur.execute("""
            SELECT activity_id, activity_type, timestamp 
            FROM activities 
            WHERE summary_polyline IS NULL 
              AND activity_type IN ('Ride', 'Run', 'Hike', 'Walk', 'VirtualRide', 'EBikeRide')
            ORDER BY timestamp DESC
            LIMIT 30;
        """)
        missing_rows = cur.fetchall()

    if not missing_rows:
        print("[Backfill-API] No outdoor activities missing polylines.")
        return 0

    print(f"[Backfill-API] Found {len(missing_rows)} outdoor activities missing polylines. Fetching from Strava...")
    token = get_valid_access_token()
    if not token:
        print("[Backfill-API] No valid Strava token available.")
        return 0

    headers = {"Authorization": f"Bearer {token}"}
    updated_count = 0

    for act_id, act_type, ts in missing_rows:
        try:
            url = f"https://www.strava.com/api/v3/activities/{act_id}"
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                map_obj = data.get("map") or {}
                poly = map_obj.get("summary_polyline") if isinstance(map_obj, dict) else None
                if poly:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE activities SET summary_polyline = %s WHERE activity_id = %s;", (poly, act_id))
                        conn.commit()
                    updated_count += 1
                    print(f"  > Updated activity {act_id} ({act_type} on {ts}): polyline length {len(poly)}")
        except Exception as e:
            print(f"  > Error fetching {act_id}: {e}")

    print(f"[Backfill-API] Synced {updated_count} polylines from live Strava API.")
    return updated_count


def main():
    print("=" * 60)
    print("Strava Route Polylines Backfill")
    print("=" * 60)

    conn = get_db_connection()
    if not conn:
        print("[ERROR] Could not connect to PostgreSQL database.")
        sys.exit(1)

    try:
        ensure_schema(conn)
        json_path = os.path.join(project_root, "activities.json")
        count_json = backfill_polylines_from_json(conn, json_path)
        count_api = backfill_missing_via_api(conn)
        
        # Invalidate caches so queries pick up fresh polylines
        from cache_manager import invalidate_all_caches
        invalidate_all_caches()

        # Verify count of populated polylines
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM activities WHERE summary_polyline IS NOT NULL;")
            total_with_poly = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM activities;")
            total_acts = cur.fetchone()[0]

        print(f"\n[Summary] Total activities with GPS routes: {total_with_poly} / {total_acts} ({total_with_poly/total_acts*100:.1f}%)")
        print("=" * 60)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

