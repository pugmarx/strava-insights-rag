import os
import sys
import json
import psycopg2
from psycopg2.extras import execute_batch

# Ensure backend directory is in path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from token_manager import get_db_connection


def backfill_elevation():
    """Alters the activities table and backfills elevation_gain from activities.json."""
    activities_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "activities.json")
    if not os.path.exists(activities_path):
        print(f"Error: Could not find {activities_path}")
        return

    with open(activities_path, "r") as f:
        activities = json.load(f)

    print(f">> Loaded {len(activities)} activities from activities.json.")

    conn = get_db_connection()
    if not conn:
        print("Error: Could not connect to database.")
        return

    try:
        with conn.cursor() as cur:
            # 1. Add column if not exists
            print(">> Ensuring elevation_gain column exists in database...")
            cur.execute("ALTER TABLE activities ADD COLUMN IF NOT EXISTS elevation_gain FLOAT DEFAULT 0;")
            conn.commit()

            # 2. Prepare batch update records
            update_data = []
            for act in activities:
                act_id = act.get("id")
                elev = float(act.get("total_elevation_gain") or 0.0)
                if act_id:
                    update_data.append((elev, act_id))

            print(f">> Updating elevation_gain for {len(update_data)} activities in Supabase...")
            update_sql = "UPDATE activities SET elevation_gain = %s WHERE activity_id = %s;"
            execute_batch(cur, update_sql, update_data, page_size=200)
            conn.commit()
            print(">> Batch update complete!")

            # 3. Verification query: Top 5 biggest climbs
            print("\n" + "=" * 50)
            print("VERIFICATION: Top 5 Biggest Climbs in Database:")
            print("=" * 50)
            cur.execute("""
                SELECT activity_type, distance, duration, elevation_gain, timestamp
                FROM activities
                WHERE elevation_gain > 0
                ORDER BY elevation_gain DESC
                LIMIT 5;
            """)
            rows = cur.fetchall()
            for r in rows:
                act_type, dist, dur, elev, ts = r
                dist_km = (dist / 1000.0) if dist else 0.0
                dur_str = f"{dur // 3600}h {(dur % 3600) // 60}m" if dur else "-"
                date_str = ts.strftime('%Y-%m-%d') if ts else 'Unknown'
                print(f"• {act_type} on {date_str}: Elevation Gain = {elev:.0f}m | Distance = {dist_km:.1f}km | Duration = {dur_str}")

            print("=" * 50)

    except Exception as e:
        print(f"Error during backfill: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    backfill_elevation()
