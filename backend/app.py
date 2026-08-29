import os
import sys
import threading

# Ensure backend directory is in python path
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, ".env"))
load_dotenv()

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from sql_rag import handle_rag_query, hybrid_query_handler
from strava_service import sync_single_activity, delete_activity, sync_incremental, get_latest_activity_timestamp
from token_manager import get_db_connection
from cache_manager import init_cache_table, invalidate_all_caches
from version import __version__, BUILD_VERSION

# Initialize Flask app
app = Flask(__name__)
CORS(app)

@app.after_request
def add_version_headers(response):
    """Add version header to every HTTP response."""
    response.headers["X-App-Version"] = BUILD_VERSION
    return response

STRAVA_VERIFY_TOKEN = os.getenv("STRAVA_VERIFY_TOKEN", "STRAVA_INSIGHTS_WEBHOOK_VERIFY_TOKEN")

def _init_db_schema():
    """Ensure elevation_gain column and query_cache table exist on startup."""
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE activities ADD COLUMN IF NOT EXISTS elevation_gain FLOAT DEFAULT 0;")
                conn.commit()
                print("[DB] Schema verified: elevation_gain column active.")
        except Exception as e:
            print(f"[DB] Schema migration check note: {e}")
        finally:
            conn.close()
    
    # Initialize query_cache table
    init_cache_table()

# Run non-blocking schema check
threading.Thread(target=_init_db_schema, daemon=True).start()


@app.route("/")
def index():
    """Serve the frontend HTML file."""
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend')
    return send_from_directory(frontend_dir, 'index.html')


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint with build version information."""
    return jsonify({
        "status": "healthy",
        "version": __version__,
        "build": BUILD_VERSION,
        "approach": "RAG"
    })


@app.route("/query", methods=["POST"])
def query():
    """API endpoint to handle user questions using RAG approach."""
    data = request.get_json() or {}
    user_question = data.get("question", "").strip()
    if not user_question:
        return jsonify({"error": "No question provided"}), 400
    if len(user_question) > 500:
        return jsonify({"error": "Question is too long (maximum 500 characters)"}), 400
    
    try:
        response, chart_data = handle_rag_query(user_question, debug=True, return_chart_data=True)
        return jsonify({
            "question": user_question,
            "response": response,
            "chart_data": chart_data,
            "approach": "RAG"
        })
    except (ConnectionError, TimeoutError) as e:
        print(f"Connection error processing query: {e}")
        return jsonify({"error": "Service temporarily unavailable"}), 503
    except ValueError as e:
        print(f"Validation error processing query: {e}")
        return jsonify({"error": "Invalid query format"}), 400
    except Exception as e:
        print(f"Unexpected error processing query: {e}")
        return jsonify({"error": "Failed to process query"}), 500


@app.route("/hybrid-query", methods=["POST"])
def hybrid_query():
    """API endpoint for hybrid RAG+SQL approach."""
    data = request.get_json() or {}
    user_question = data.get("question", "").strip()
    if not user_question:
        return jsonify({"error": "No question provided"}), 400
    if len(user_question) > 500:
        return jsonify({"error": "Question is too long (maximum 500 characters)"}), 400
    
    try:
        response, chart_data = hybrid_query_handler(user_question, return_chart_data=True)
        return jsonify({
            "question": user_question,
            "response": response,
            "chart_data": chart_data,
            "approach": "Hybrid RAG+SQL"
        })
    except (ConnectionError, TimeoutError) as e:
        print(f"Connection error processing hybrid query: {e}")
        return jsonify({"error": "Service temporarily unavailable"}), 503
    except ValueError as e:
        print(f"Validation error processing hybrid query: {e}")
        return jsonify({"error": "Invalid query format"}), 400
    except Exception as e:
        print(f"Unexpected error processing hybrid query: {e}")
        return jsonify({"error": "Failed to process query"}), 500


# ---------------------------------------------------------------------------
# Strava Webhook Handlers
# ---------------------------------------------------------------------------

@app.route("/strava/webhook", methods=["GET"])
def strava_webhook_handshake():
    """
    Handle Strava's subscription challenge handshake.
    Strava sends GET request with:
      hub.mode=subscribe
      hub.challenge=xxx
      hub.verify_token=yyy
    """
    hub_mode = request.args.get("hub.mode")
    hub_challenge = request.args.get("hub.challenge")
    hub_verify_token = request.args.get("hub.verify_token")

    if hub_mode == "subscribe" and hub_challenge:
        if hub_verify_token and hub_verify_token != STRAVA_VERIFY_TOKEN:
            print(f"[Webhook] Verification token mismatch: got {hub_verify_token}")
            return jsonify({"error": "Invalid verify token"}), 403

        print(f"[Webhook] Handshake verified! Responding with challenge: {hub_challenge}")
        return jsonify({"hub.challenge": hub_challenge}), 200

    return jsonify({"error": "Invalid subscription request"}), 400


def _process_webhook_event_async(event_data):
    """Background worker to process Strava webhook payload without delaying HTTP 200 response."""
    try:
        object_type = event_data.get("object_type")
        aspect_type = event_data.get("aspect_type")
        object_id = event_data.get("object_id")

        print(f"[Webhook Async] Received event: {object_type}.{aspect_type} for ID {object_id}")

        if object_type == "activity":
            if aspect_type in ("create", "update"):
                sync_single_activity(object_id)
            elif aspect_type == "delete":
                delete_activity(object_id)
    except Exception as e:
        print(f"[Webhook Async] Error processing webhook event: {e}")


@app.route("/strava/webhook", methods=["POST"])
def strava_webhook_event():
    """
    Receive real-time push events from Strava when activities are created/updated/deleted.
    Must respond with HTTP 200 within 2 seconds.
    """
    event_data = request.get_json() or {}
    print(f"[Webhook] Event payload: {event_data}")

    # Process in background thread so response returns immediately
    thread = threading.Thread(target=_process_webhook_event_async, args=(event_data,), daemon=True)
    thread.start()

    return jsonify({"status": "received"}), 200


# ---------------------------------------------------------------------------
# On-Demand Sync Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/sync", methods=["POST"])
def trigger_sync():
    """Trigger on-demand incremental sync of latest Strava activities."""
    try:
        data = request.get_json(silent=True) or {}
        limit = int(data.get("limit", 50))
        result = sync_incremental(limit=limit)
        return jsonify(result), 200
    except Exception as e:
        print(f"[Sync API] Error during sync: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/sync/status", methods=["GET"])
def sync_status():
    """Get database sync statistics (total activities & latest timestamp)."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), MAX(timestamp) FROM activities")
            row = cur.fetchone()
            total_activities = row[0] if row else 0
            latest_val = row[1] if row else None
            if hasattr(latest_val, "isoformat"):
                latest_timestamp = latest_val.isoformat()
            else:
                latest_timestamp = str(latest_val) if latest_val else None

            return jsonify({
                "total_activities": total_activities,
                "latest_timestamp": latest_timestamp
            }), 200
    except Exception as e:
        print(f"[Sync Status] Query error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Analytics & Breakthroughs Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/analytics/breakthroughs", methods=["GET"])
def analytics_breakthroughs():
    """Return statistical clusters, climbing breakthroughs, and anomalies for charting."""
    from analytics import get_breakthrough_analytics
    activity_type = request.args.get("type")
    data = get_breakthrough_analytics(activity_filter=activity_type)
    return jsonify(data), 200


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    """Manually invalidate both in-memory and database query caches."""
    try:
        invalidate_all_caches()
        return jsonify({"status": "success", "message": "All caches cleared"}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"[App] Starting Strava Insights RAG ({BUILD_VERSION}) on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
