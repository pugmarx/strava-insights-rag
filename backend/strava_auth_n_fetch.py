import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Read values
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TOKEN_FILE = "token.json"  # Store tokens in a file

def get_saved_token():
    """Load the last saved access token from a file, handling missing or invalid data."""
    if not os.path.exists(TOKEN_FILE):
        return None  # File does not exist

    try:
        with open(TOKEN_FILE, "r") as file:
            token_data = json.load(file)
            if not isinstance(token_data, dict):  # Ensure it's a dictionary
                raise ValueError("Invalid token format")
            return token_data
    except (json.JSONDecodeError, ValueError):
        print("Warning: token.json is empty or corrupted. Deleting it.")
        os.remove(TOKEN_FILE)  # Remove invalid file
        return None  # No valid token available

def save_token(token_data):
    """Save the new access and refresh tokens to a file."""
    with open(TOKEN_FILE, "w") as file:
        json.dump(token_data, file)

def refresh_access_token():
    """Refresh the access token using the refresh token."""
    token_data = get_saved_token()
    if not token_data or "refresh_token" not in token_data:
        print("No refresh token available. Please authenticate again.")
        return None

    url = "https://www.strava.com/api/v3/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": token_data["refresh_token"],
        "grant_type": "refresh_token",
    }
    
    response = requests.post(url, data=payload)
    
    if response.status_code == 200:
        new_token_data = response.json()
        save_token(new_token_data)
        print("Access token refreshed successfully.")
        return new_token_data["access_token"]
    else:
        print("Error refreshing token:", response.json())
        return None

def get_access_token():
    """Retrieve the access token, refreshing if expired."""
    token_data = get_saved_token()
    
    if not token_data or "access_token" not in token_data:
        print("No saved access token. Please authenticate.")
        return None
    
    return token_data["access_token"]

def fetch_strava_activities():
    """Fetch activities from Strava using the latest access token."""
    access_token = get_access_token()  # Automatically get a valid token
    if not access_token:
        print("No valid access token. Cannot fetch activities.")
        return []

    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"per_page": 200, "page": 1}
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        activities = response.json()
        return activities
    elif response.status_code == 401:  # Token expired, refresh and retry
        print("Access token expired. Refreshing...")
        access_token = refresh_access_token()
        if not access_token:
            print("Failed to refresh access token. Cannot fetch activities.")
            return []

        headers["Authorization"] = f"Bearer {access_token}"
        response = requests.get(url, headers=headers)
        return response.json() if response.status_code == 200 else {"error": response.json()}
    else:
        return {"error": response.json()}

# Example Usage
activities = fetch_strava_activities()
if isinstance(activities, list):
    json.dump(activities, open("activities.json", "w"), indent=2)  # Save to a file
    print("Activities fetched:", len(activities))
    for activity in activities[:5]:  # Print first 5 activities
        print(f"{activity['name']} - {activity['type']} - {activity['distance']} meters")
else:
    print("Error fetching activities:", activities)