#!/usr/bin/env python3
"""
Backfill script to update historical activities in PostgreSQL with Strava's native moving_time
and elapsed_time.

3-Stage Synchronization:
1. Local activities.json file (fast bulk update for existing export records).
2. Live Strava API v3 for database records not in activities.json or lacking elapsed_time.
3. Live Strava Incremental Sync for brand new workouts recorded after the last sync.
"""

import sys
import os
import time
import json
import argparse
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_batch

# Set python path to find backend modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UTILS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(UTILS_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from token_manager import get_db_connection
from strava_service import fetch_activity_from_strava, format_activity_text, sync_incremental
from sql_rag import compute_embedding
from cache_manager import invalidate_all_caches


def backfill_from_local_json(dry_run=False):
    """Stage 1: Backfill moving_time and elapsed_time from activities.json if present."""
    json_path = os.path.join(PROJECT_ROOT, "activities.json")
    if not os.path.exists(json_path):
        print(f"[Stage 1] No local activities.json found at {json_path}. Skipping.")
        return set()

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Stage 1] Could not read {json_path}: {e}")
        return set()

    if not isinstance(data, list):
        return set()

    print(f"\n[Stage 1] Found {len(data)} activities in local activities.json.")
    update_batch = []
    processed_ids = set()

    for item in data:
        act_id = item.get("id")
        if not act_id:
            continue
        processed_ids.add(act_id)
        moving_time = int(item.get("moving_time") or item.get("elapsed_time") or 0)
        elapsed_time = int(item.get("elapsed_time") or moving_time)
        update_batch.append((moving_time, elapsed_time, act_id))

    if dry_run:
        print(f"[DRY RUN] Would batch update {len(update_batch)} activities from activities.json.")
        return processed_ids

    conn = get_db_connection()
    if not conn:
        print("[Stage 1] Could not connect to database.")
        return set()

    try:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE activities ADD COLUMN IF NOT EXISTS elapsed_time INT;")
            update_sql = "UPDATE activities SET duration = %s, elapsed_time = %s WHERE activity_id = %s;"
            execute_batch(cur, update_sql, update_batch, page_size=250)
            conn.commit()
            print(f"[Stage 1] Successfully batch updated {len(update_batch)} activities from activities.json!")
            return processed_ids
    except Exception as e:
        print(f"[Stage 1] Error during local batch update: {e}")
        return set()
    finally:
        conn.close()


def backfill_remaining_from_api(processed_ids, limit=None, dry_run=False, sleep_sec=0.2):
    """Stage 2: Fetch any database activities not in activities.json directly from Strava API."""
    conn = get_db_connection()
    if not conn:
        print("[Stage 2] Could not connect to database.")
        return

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT activity_id, activity_type, distance, duration, timestamp FROM activities ORDER BY timestamp DESC;")
            all_db_rows = cur.fetchall()
    finally:
        conn.close()

    remaining = [r for r in all_db_rows if r[0] not in processed_ids]
    if limit:
        remaining = remaining[:int(limit)]

    print(f"\n[Stage 2] {len(remaining)} activities in DB need live Strava API detail sync.")
    if not remaining:
        print("[Stage 2] All existing database activities are already up to date!")
        return

    conn = get_db_connection()
    if not conn:
        return

    updated_count = 0
    error_count = 0

    try:
        for idx, row in enumerate(remaining, 1):
            act_id, act_type, dist_m, old_dur, ts = row
            try:
                print(f"[{idx}/{len(remaining)}] Fetching activity {act_id} from Strava API...")
                strava_data = fetch_activity_from_strava(act_id)
                moving_time = int(strava_data.get("moving_time") or strava_data.get("elapsed_time") or 0)
                elapsed_time = int(strava_data.get("elapsed_time") or moving_time)

                if dry_run:
                    print(f"   [DRY RUN] Would update {act_id}: duration={moving_time}s, elapsed={elapsed_time}s")
                    updated_count += 1
                else:
                    new_text = format_activity_text(strava_data)
                    new_emb = compute_embedding(new_text)

                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE activities
                            SET duration = %s,
                                elapsed_time = %s,
                                embedding = %s
                            WHERE activity_id = %s;
                        """, (moving_time, elapsed_time, new_emb, act_id))
                        conn.commit()
                    updated_count += 1

                time.sleep(sleep_sec)
            except Exception as e:
                print(f"   [Error] Failed to update activity {act_id}: {e}")
                error_count += 1
    finally:
        conn.close()

    print(f"[Stage 2] API detail sync complete. Updated: {updated_count}, Errors: {error_count}")


def sync_brand_new_activities(dry_run=False):
    """Stage 3: Pull down any newly completed workouts from Strava not yet in database."""
    if dry_run:
        print("\n[Stage 3] [DRY RUN] Would check for new activities via incremental sync.")
        return
    print("\n[Stage 3] Checking for newly completed Strava activities...")
    try:
        res = sync_incremental(limit=50)
        print(f"[Stage 3] Incremental sync finished: Synced {res.get('synced_count', 0)} new activities.")
    except Exception as e:
        print(f"[Stage 3] Incremental sync note: {e}")


def main():
    parser = argparse.ArgumentParser(description="Backfill Strava moving_time & elapsed_time into PostgreSQL")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of API calls")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing to database")
    parser.add_argument("--api-only", action="store_true", help="Skip local activities.json and use API only")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep seconds between API calls (default: 0.2)")
    args = parser.parse_args()

    processed = set()
    if not args.api_only:
        processed = backfill_from_local_json(dry_run=args.dry_run)

    backfill_remaining_from_api(processed_ids=processed, limit=args.limit, dry_run=args.dry_run, sleep_sec=args.sleep)
    sync_brand_new_activities(dry_run=args.dry_run)

    if not args.dry_run:
        invalidate_all_caches()
        print("\n" + "=" * 60)
        print("✅ Backfill Complete! All activities and caches are now in-sync with Strava.")
        print("=" * 60)


if __name__ == "__main__":
    main()
