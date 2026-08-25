import os
import time
import requests
import json

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

TOKEN_FILE = "token.json"
ACTIVITIES_FILE = "activities.json"

CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")

TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"


def load_tokens():
    with open(TOKEN_FILE, "r") as f:
        return json.load(f)


def save_tokens(token_data):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)


def refresh_token_if_needed(tokens):
    if time.time() < tokens["expires_at"]:
        print(">> Access token is still valid.")
        return tokens

    print(">> Access token expired. Refreshing...")

    response = requests.post(TOKEN_URL, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"]
    })

    if response.status_code != 200:
        raise Exception(f"Token refresh failed: {response.status_code}, {response.text}")

    new_tokens = response.json()
    refreshed = {
        "access_token": new_tokens["access_token"],
        "refresh_token": new_tokens["refresh_token"],
        "expires_at": new_tokens["expires_at"],
        "expires_in": new_tokens["expires_in"],
        "token_type": new_tokens["token_type"]
    }

    save_tokens(refreshed)
    print(">> Token refreshed and saved.")
    return refreshed


def fetch_activities(access_token, per_page=100, max_pages=10):
    headers = {"Authorization": f"Bearer {access_token}"}
    all_activities = []

    for page in range(1, max_pages + 1):
        print(f"Fetching page {page} (up to {per_page} activities)...")
        res = requests.get(ACTIVITIES_URL, headers=headers, params={
            "per_page": per_page,
            "page": page
        })

        # Strava rate limit headers: 'X-RateLimit-Usage' (e.g. '10,50')
        usage = res.headers.get("X-RateLimit-Usage")
        limit = res.headers.get("X-RateLimit-Limit")
        if usage and limit:
            print(f"  [Rate Limit: {usage} used out of {limit}]")

        if res.status_code == 429:
            print("⚠️ Rate limit exceeded (429). Stopping fetch.")
            break

        if res.status_code != 200:
            print(f"ERROR: Error fetching page {page}: HTTP {res.status_code}")
            print(f"  Response: {res.text}")
            if res.status_code == 403:
                print("\n⚠️  HTTP 403 Forbidden: Your Strava access token is missing activity permissions ('activity:read_all').")
                print("To fix:")
                print("1. Re-run 'python utils/strava/first_auth.py'")
                print("2. When the Strava webpage opens, make sure to check the box: 'View data about your activities'")
            break

        page_data = res.json()
        if not page_data:
            print(f"  No more activities on page {page}.")
            break

        all_activities.extend(page_data)
        time.sleep(0.5)  # Gentle 500ms pause between pages

    print(f">> Total activities fetched: {len(all_activities)}")
    return all_activities


def main():
    tokens = load_tokens()
    tokens = refresh_token_if_needed(tokens)
    access_token = tokens["access_token"]

    activities = fetch_activities(access_token)
    with open(ACTIVITIES_FILE, "w") as f:
        json.dump(activities, f, indent=2)

    print(f">> Activities saved to {ACTIVITIES_FILE}")


if __name__ == "__main__":
    main()
