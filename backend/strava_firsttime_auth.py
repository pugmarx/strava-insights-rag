import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Read values
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8080"  # Must match your Strava app settings
TOKEN_FILE = "token.json"  # File to store tokens

def get_auth_url():
    """Generate Strava authorization URL with full activity permissions."""
    return (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=read,activity:read,activity:read_all"
        f"&approval_prompt=force"
    )

def exchange_code_for_token(auth_code):
    """Exchange the authorization code for an access token."""
    url = "https://www.strava.com/api/v3/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": auth_code,
        "grant_type": "authorization_code",
    }
    response = requests.post(url, data=payload)
    
    if response.status_code == 200:
        token_data = response.json()
        save_token(token_data)
        return token_data["access_token"]
    else:
        print("Error exchanging code:", response.json())
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
        json.dump(token_data, file)

def refresh_access_token():
    """Refresh the access token using the refresh token."""
    token_data = get_saved_token()
    if not token_data or "refresh_token" not in token_data:
        print("No refresh token available.")
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

# def fetch_strava_activities():
#     """Fetch activities from Strava using the latest access token."""
#     access_token = get_access_token()
#     if not access_token:
#         return {"error": "No valid access token available."}
    
#     url = "https://www.strava.com/api/v3/athlete/activities"
#     headers = {"Authorization": f"Bearer {access_token}"}

#     response = requests.get(url, headers=headers)
    
#     if response.status_code == 200:
#         return response.json()  # Return activity data
#     elif response.status_code == 401:  # Token expired, refresh and retry
#         print("Access token expired. Refreshing...")
#         access_token = refresh_access_token()
#         if not access_token:
#             return {"error": "Failed to refresh access token."}
        
#         headers["Authorization"] = f"Bearer {access_token}"
#         response = requests.get(url, headers=headers)
#         return response.json() if response.status_code == 200 else {"error": response.json()}
#     else:
#         return {"error": response.json()}

# 🚀 First Step: Open this URL and authorize your app
print("🔗 Open this URL in your browser and approve access:")
print(get_auth_url())

# 🔹 After authorizing, manually enter the code from the redirect URL
auth_code = input("\n🔑 Enter the authorization code from Strava: ").strip()
exchange_code_for_token(auth_code)  # Exchange the code and save tokens

# # 🔹 Fetch and print activities
# activities = fetch_strava_activities()
# if "error" not in activities:
#     for activity in activities[:5]:  # Print first 5 activities
#         print(f"{activity['name']} - {activity['type']} - {activity['distance']} meters")
# else:
#     print("Error:", activities["error"])
