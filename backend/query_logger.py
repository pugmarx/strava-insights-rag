import os
import json
import time
import threading
from datetime import datetime, timedelta
import psycopg2
from token_manager import get_db_connection

# Project root directory for local audit log fallback
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
AUDIT_LOG_FILE = os.path.join(LOGS_DIR, "query_audit.jsonl")


def _ensure_logs_dir():
    """Ensure local logs directory exists for audit fallback."""
    os.makedirs(LOGS_DIR, exist_ok=True)


def init_query_log_table():
    """Ensure query_logs table and indices exist in PostgreSQL with RLS enabled."""
    conn = get_db_connection()
    if not conn:
        print("[QueryLogger] Warning: Could not connect to database to initialize query_logs table.")
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS query_logs (
                    id SERIAL PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    approach VARCHAR(30) DEFAULT 'rag',
                    status VARCHAR(30) NOT NULL,
                    retrieved_count INT DEFAULT 0,
                    error_message TEXT,
                    response_preview TEXT,
                    latency_ms INT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS query_logs_status_idx ON query_logs (status);
                CREATE INDEX IF NOT EXISTS query_logs_created_at_idx ON query_logs (created_at);

                ALTER TABLE IF EXISTS query_logs ENABLE ROW LEVEL SECURITY;
            """)
            conn.commit()
            print("[QueryLogger] query_logs table verified with RLS enabled.")
            return True
    except psycopg2.Error as e:
        print(f"[QueryLogger] Error initializing query_logs table: {e}")
        return False
    finally:
        conn.close()


def _write_local_audit_log(entry):
    """Append query log entry to local JSONL file."""
    try:
        _ensure_logs_dir()
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        print(f"[QueryLogger] Local JSONL log error: {e}")


def _save_log_to_db(query_text, approach, status, retrieved_count, error_message, response_preview, latency_ms, timestamp_iso):
    """Internal helper to insert log entry into PostgreSQL."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO query_logs (
                    query_text, approach, status, retrieved_count, error_message, response_preview, latency_ms
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                query_text,
                approach,
                status,
                retrieved_count,
                error_message,
                response_preview,
                latency_ms
            ))
            conn.commit()
            return True
    except psycopg2.Error as e:
        print(f"[QueryLogger] DB log insertion failed: {e}")
        return False
    finally:
        conn.close()


def log_query_event(query_text, approach="rag", status="SUCCESS", retrieved_count=0, error_message=None, response=None, latency_ms=None, async_log=True):
    """
    Log a query execution event into PostgreSQL and local JSONL audit file.
    Status can be: 'SUCCESS', 'NO_RESULTS', 'ERROR', 'UNRECOGNIZED'.
    """
    if not query_text:
        return

    # Trim response preview
    response_preview = None
    if response:
        cleaned = str(response).strip().replace("\n", " ")
        response_preview = cleaned[:300] + ("..." if len(cleaned) > 300 else "")

    now_iso = datetime.utcnow().isoformat()
    entry = {
        "timestamp": now_iso,
        "query_text": query_text,
        "approach": approach,
        "status": status,
        "retrieved_count": retrieved_count,
        "error_message": str(error_message) if error_message else None,
        "response_preview": response_preview,
        "latency_ms": latency_ms
    }

    def _worker():
        _write_local_audit_log(entry)
        _save_log_to_db(
            query_text=query_text,
            approach=approach,
            status=status,
            retrieved_count=retrieved_count,
            error_message=str(error_message) if error_message else None,
            response_preview=response_preview,
            latency_ms=latency_ms,
            timestamp_iso=now_iso
        )

    if async_log:
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
    else:
        _worker()


def fetch_failed_queries(limit=50, days=7):
    """Retrieve recent failed or zero-result queries."""
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, query_text, approach, status, retrieved_count, error_message, latency_ms, created_at
                    FROM query_logs
                    WHERE status != 'SUCCESS' AND created_at >= NOW() - INTERVAL '%s days'
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (days, limit))
                rows = cur.fetchall()
                results = []
                for r in rows:
                    results.append({
                        "id": r[0],
                        "query_text": r[1],
                        "approach": r[2],
                        "status": r[3],
                        "retrieved_count": r[4],
                        "error_message": r[5],
                        "latency_ms": r[6],
                        "created_at": r[7].isoformat() if hasattr(r[7], "isoformat") else str(r[7])
                    })
                return results
        except Exception as e:
            print(f"[QueryLogger] DB fetch failed: {e}")
        finally:
            conn.close()

    # Fallback to local JSONL
    results = []
    if os.path.exists(AUDIT_LOG_FILE):
        cutoff = datetime.utcnow() - timedelta(days=days)
        try:
            with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if item.get("status") != "SUCCESS":
                        ts_str = item.get("timestamp")
                        if ts_str:
                            try:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                if ts.replace(tzinfo=None) >= cutoff:
                                    results.append(item)
                            except Exception:
                                results.append(item)
                        else:
                            results.append(item)
        except Exception as e:
            print(f"[QueryLogger] Error reading audit file: {e}")

    results.reverse()
    return results[:limit]


def get_query_health_summary(days=7):
    """Aggregate health summary of queries over the past N days."""
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'SUCCESS') as success_count,
                        COUNT(*) FILTER (WHERE status = 'NO_RESULTS') as no_results_count,
                        COUNT(*) FILTER (WHERE status = 'ERROR') as error_count,
                        COUNT(*) FILTER (WHERE status = 'UNRECOGNIZED') as unrecognized_count,
                        AVG(latency_ms) as avg_latency
                    FROM query_logs
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                """, (days,))
                row = cur.fetchone()
                total = row[0] or 0
                success = row[1] or 0
                no_results = row[2] or 0
                errors = row[3] or 0
                unrecognized = row[4] or 0
                avg_latency = round(float(row[5]), 1) if row[5] is not None else 0

                cur.execute("""
                    SELECT query_text, COUNT(*) as freq, status, MAX(error_message)
                    FROM query_logs
                    WHERE status != 'SUCCESS' AND created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY query_text, status
                    ORDER BY freq DESC
                    LIMIT 10
                """, (days,))
                top_failures = [{
                    "query_text": f_row[0],
                    "count": f_row[1],
                    "status": f_row[2],
                    "error_message": f_row[3]
                } for f_row in cur.fetchall()]

                return {
                    "period_days": days,
                    "total_queries": total,
                    "successful_queries": success,
                    "no_results_queries": no_results,
                    "error_queries": errors,
                    "unrecognized_queries": unrecognized,
                    "success_rate_percent": round((success / total * 100), 1) if total > 0 else 100.0,
                    "avg_latency_ms": avg_latency,
                    "top_failed_queries": top_failures
                }
        except Exception as e:
            print(f"[QueryLogger] DB summary failed: {e}")
        finally:
            conn.close()

    # Fallback to local JSONL
    total = 0
    success = 0
    no_results = 0
    errors = 0
    unrecognized = 0
    failure_counts = {}
    latencies = []

    if os.path.exists(AUDIT_LOG_FILE):
        cutoff = datetime.utcnow() - timedelta(days=days)
        try:
            with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    total += 1
                    status = item.get("status", "SUCCESS")
                    if status == "SUCCESS":
                        success += 1
                    elif status == "NO_RESULTS":
                        no_results += 1
                        q = item.get("query_text", "")
                        failure_counts[q] = failure_counts.get(q, 0) + 1
                    elif status == "ERROR":
                        errors += 1
                        q = item.get("query_text", "")
                        failure_counts[q] = failure_counts.get(q, 0) + 1
                    elif status == "UNRECOGNIZED":
                        unrecognized += 1
                        q = item.get("query_text", "")
                        failure_counts[q] = failure_counts.get(q, 0) + 1

                    if item.get("latency_ms"):
                        latencies.append(item["latency_ms"])
        except Exception as e:
            print(f"[QueryLogger] Error reading audit file for summary: {e}")

    top_failed = [{"query_text": q, "count": count, "status": "FAILED"} for q, count in sorted(failure_counts.items(), key=lambda x: x[1], reverse=True)[:10]]

    return {
        "period_days": days,
        "total_queries": total,
        "successful_queries": success,
        "no_results_queries": no_results,
        "error_queries": errors,
        "unrecognized_queries": unrecognized,
        "success_rate_percent": round((success / total * 100), 1) if total > 0 else 100.0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "top_failed_queries": top_failed
    }
