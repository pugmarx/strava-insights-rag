import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(project_root / ".env")

from garminconnect import Garmin

def diagnose():
    token_dir = project_root / ".garmin_tokens"
    client = Garmin()
    client.login(str(token_dir))

    print("--- User Profile & Settings ---")
    try:
        profile = client.garth.profile
        print(f"Profile: {profile}")
    except Exception as e:
        print(f"Error fetching profile: {e}")

    print("\n--- Registered Devices ---")
    try:
        devices = client.get_devices()
        print(f"Devices count: {len(devices)}")
        for d in devices:
            print(f"  Device: {d.get('productDisplayName', 'Unknown')} (ID: {d.get('deviceId')}, Serial: {d.get('partNumber')})")
    except Exception as e:
        print(f"Error fetching devices: {e}")

    print("\n--- Last Activity ---")
    try:
        last = client.get_last_activity()
        print(f"Last activity: {last}")
    except Exception as e:
        print(f"Error fetching last activity: {e}")

    print("\n--- Today's Stats ---")
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        stats = client.get_user_summary(today)
        print(f"Total Steps today: {stats.get('totalSteps', 0)}, Distance: {stats.get('totalDistanceMeters', 0)}")
    except Exception as e:
        print(f"Error fetching today stats: {e}")

if __name__ == "__main__":
    diagnose()
