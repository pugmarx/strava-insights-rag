import requests
import json
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Read values
STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8080"  # Must match your Strava app settings
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "token.json")

# Add backend directory to sys.path to access token_manager if available
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


def validate_credentials():
    global STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET
    if not STRAVA_CLIENT_ID or "GET_FROM_STRAVA" in STRAVA_CLIENT_ID or not STRAVA_CLIENT_SECRET or "GET_FROM_STRAVA" in STRAVA_CLIENT_SECRET:
        print("\n⚠️  Missing or invalid STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET in .env file!")
        print("You can find your numeric Client ID and Client Secret at: https://www.strava.com/settings/api\n")
        
        if not STRAVA_CLIENT_ID or "GET_FROM_STRAVA" in STRAVA_CLIENT_ID:
            STRAVA_CLIENT_ID = input("👉 Enter your Strava Client ID (numeric, e.g. 123456): ").strip()
        if not STRAVA_CLIENT_SECRET or "GET_FROM_STRAVA" in STRAVA_CLIENT_SECRET:
            STRAVA_CLIENT_SECRET = input("👉 Enter your Strava Client Secret: ").strip()


def get_auth_url():
    """Generate Strava authorization URL with full activity permissions."""
    return (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=read,activity:read,activity:read_all"
        f"&approval_prompt=force"
    )


def exchange_code_for_token(auth_code):
    """Exchange the authorization code for an access token and refresh token."""
    url = "https://www.strava.com/api/v3/oauth/token"
    payload = {
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "code": auth_code,
        "grant_type": "authorization_code",
    }
    response = requests.post(url, data=payload)
    
    if response.status_code == 200:
        token_data = response.json()
        save_token(token_data)

        # Also persist to Supabase if token_manager is importable
        try:
            from token_manager import save_tokens_to_db
            saved_db = save_tokens_to_db({
                "athlete_id": token_data.get("athlete", {}).get("id"),
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
                "expires_at": token_data.get("expires_at", 0)
            })
            if saved_db:
                print("✅ Tokens successfully synced to Supabase database!")
        except Exception as e:
            print(f"ℹ️ (Note: Could not save to DB directly: {e})")

        print(f"✅ Token saved to {TOKEN_FILE}")
        return token_data["access_token"]
    else:
        print("❌ Error exchanging code:", response.json())
        return None


def get_saved_token():
    """Load the last saved access token from a file."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as file:
            return json.load(file)
    return None


def save_token(token_data):
    """Save the new access and refresh tokens to a file."""
    with open(TOKEN_FILE, "w") as file:
        json.dump(token_data, file, indent=2)


if __name__ == "__main__":
    validate_credentials()
    
    print("\n🔗 Step 1: Open this URL in your browser and approve access:")
    print("-" * 70)
    print(get_auth_url())
    print("-" * 70)
    
    print("\n👉 Step 2: After clicking 'Authorize', your browser will redirect to a URL like:")
    print("   http://localhost:8080/?state=&code=YOUR_CODE_HERE&scope=...")
    print("   (It's fine if the page says 'Unable to connect' or 'Site can't be reached')")
    
    auth_code = input("\n🔑 Step 3: Copy & paste the 'code' parameter from your browser address bar here: ").strip()
    if auth_code:
        exchange_code_for_token(auth_code)
    else:
        print("❌ No authorization code entered.")