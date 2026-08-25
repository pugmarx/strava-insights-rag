import os
import time
import json
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "token.json")

CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
ATHLETE_ID = os.getenv("STRAVA_USER_ID")

POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_SSLMODE = os.getenv("POSTGRES_SSLMODE", "require")


def get_db_connection():
    """Establish a direct PostgreSQL database connection."""
    try:
        return psycopg2.connect(
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            sslmode=POSTGRES_SSLMODE
        )
    except Exception as e:
        print(f"[TokenManager] DB connection error: {e}")
        return None


def get_tokens_from_db():
    """Load Strava tokens stored in PostgreSQL."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT athlete_id, access_token, refresh_token, expires_at 
                FROM strava_tokens 
                WHERE id = 1
            """)
            row = cur.fetchone()
            if row:
                return {
                    "athlete_id": row[0],
                    "access_token": row[1],
                    "refresh_token": row[2],
                    "expires_at": int(row[3]) if row[3] else 0
                }
    except Exception as e:
        print(f"[TokenManager] Failed to read tokens from DB: {e}")
    finally:
        conn.close()
    return None


def save_tokens_to_db(token_data):
    """Save or update Strava tokens in PostgreSQL."""
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO strava_tokens (id, athlete_id, access_token, refresh_token, expires_at, updated_at)
                VALUES (1, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    athlete_id = EXCLUDED.athlete_id,
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                token_data.get("athlete_id") or ATHLETE_ID,
                token_data.get("access_token"),
                token_data.get("refresh_token"),
                token_data.get("expires_at", 0)
            ))
            conn.commit()
            return True
    except Exception as e:
        print(f"[TokenManager] Failed to save tokens to DB: {e}")
        return False
    finally:
        conn.close()


def get_tokens_from_file():
    """Load tokens from local token.json if present."""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[TokenManager] Failed to read token.json: {e}")
    return None


def save_tokens_to_file(token_data):
    """Save tokens to local token.json."""
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)
    except Exception as e:
        print(f"[TokenManager] Could not write token.json: {e}")


def refresh_strava_token(refresh_token):
    """Exchange refresh token for a new access token via Strava OAuth."""
    if not CLIENT_ID or not CLIENT_SECRET or not refresh_token:
        raise ValueError("Missing Strava CLIENT_ID, CLIENT_SECRET, or refresh_token")

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    res = requests.post(TOKEN_URL, data=payload, timeout=15)
    if res.status_code != 200:
        raise RuntimeError(f"Strava token refresh failed ({res.status_code}): {res.text}")

    data = res.json()
    new_tokens = {
        "athlete_id": data.get("athlete", {}).get("id") or ATHLETE_ID,
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_at": data.get("expires_at", 0),
        "token_type": data.get("token_type", "Bearer")
    }

    # Persist to both DB and file
    save_tokens_to_db(new_tokens)
    save_tokens_to_file(new_tokens)
    return new_tokens


def get_valid_access_token():
    """
    Retrieve a valid Strava access token, refreshing automatically if expired.
    Checks DB -> File -> Environment Variable.
    """
    token_data = get_tokens_from_db()

    if not token_data:
        token_data = get_tokens_from_file()

    if not token_data:
        env_refresh = os.getenv("STRAVA_REFRESH_TOKEN")
        if env_refresh:
            token_data = {"refresh_token": env_refresh, "expires_at": 0}

    if not token_data or not token_data.get("refresh_token"):
        raise ValueError(
            "No Strava refresh token found. Please run 'python utils/strava/first_auth.py' "
            "or set STRAVA_REFRESH_TOKEN in environment."
        )

    # Check if access token is valid (with 60-second buffer)
    current_time = time.time()
    expires_at = token_data.get("expires_at", 0)
    access_token = token_data.get("access_token")

    if access_token and current_time < (expires_at - 60):
        return access_token

    # Token is expired or missing access_token, refresh it
    print("[TokenManager] Access token expired or missing. Refreshing...")
    new_tokens = refresh_strava_token(token_data["refresh_token"])
    return new_tokens["access_token"]
