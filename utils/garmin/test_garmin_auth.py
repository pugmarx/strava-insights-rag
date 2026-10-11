import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(project_root / ".env")

try:
    from garminconnect import Garmin
except ImportError:
    print("Error: garminconnect is not installed in the current environment.")
    print("Run: ./venv/bin/pip install garminconnect")
    sys.exit(1)


def test_garmin_connection():
    token_dir = project_root / ".garmin_tokens"
    email = os.getenv("GARMIN_EMAIL", "").strip()
    password = os.getenv("GARMIN_PASSWORD", "").strip()

    print("==================================================")
    print(" Garmin Connect Authentication & Activity Test")
    print("==================================================")

    client = None

    # Step 1: Check if saved session tokens exist
    if token_dir.exists() and any(token_dir.iterdir()):
        print(f"\n[1/3] Found existing session tokens in: {token_dir}")
        try:
            client = Garmin()
            print("Attempting login using stored session tokens...")
            client.login(str(token_dir))
            print(">> Successfully authenticated with cached session tokens!")
        except Exception as e:
            print(f"Warning: Failed to authenticate with stored tokens ({e}). Falling back to credentials...")
            client = None

    # Step 2: Login with Email & Password if needed
    if client is None:
        if not email or not password:
            print("\nError: GARMIN_EMAIL and/or GARMIN_PASSWORD not found in .env")
            print("Please ensure both are set in your .env file.")
            sys.exit(1)

        masked_email = email[:3] + "***" + email[email.find("@"):] if "@" in email else "***"
        print(f"\n[1/3] Authenticating as: {masked_email}")

        client = Garmin(email=email, password=password)
        try:
            # garth.login handles MFA interactive prompt automatically if challenged
            client.login()
            print(">> Login successful!")

            # Persist tokens so we don't need credentials or MFA next time
            token_dir.mkdir(parents=True, exist_ok=True)
            client.garth.dump(str(token_dir))
            print(f">> Session tokens successfully saved to {token_dir}")
        except Exception as e:
            print(f"\n[FAIL] Authentication failed: {e}")
            print("\nTips:")
            print("1. Verify email and password in .env.")
            print("2. If Garmin sent a verification code to your email/SMS, enter it when prompted.")
            print("3. Check for any temporary rate limit blocks.")
            sys.exit(1)

    # Step 3: Fetch Profile Info
    print("\n[2/3] Fetching Profile Info...")
    try:
        display_name = client.display_name or client.get_full_name()
        print(f">> Authenticated Profile: {display_name}")
    except Exception as e:
        print(f"Warning: Could not fetch display name: {e}")

    # Step 4: Fetch Recent Activities
    print("\n[3/3] Fetching Recent Activities...")
    try:
        activities = client.get_activities(0, 5)
        if not activities:
            print(">> Query returned 0 activities.")
            print("\nNote: If activities show in your mobile app but 0 appear here:")
            print("1. Double-check that your phone app's email matches this GARMIN_EMAIL.")
            print("2. Verify your activities are synced to Garmin's cloud (pull down to refresh in app).")
            return

        print(f">> Successfully fetched {len(activities)} recent activities:\n")
        for idx, act in enumerate(activities, 1):
            act_id = act.get("activityId")
            act_name = act.get("activityName", "Untitled")
            act_type = act.get("activityType", {}).get("typeKey", "unknown")
            distance_m = act.get("distance", 0.0)
            duration_s = act.get("duration") or act.get("movingDuration", 0.0)
            elevation_m = act.get("elevationGain", 0.0)
            start_time = act.get("startTimeLocal", act.get("startTimeGMT", "unknown"))

            distance_km = distance_m / 1000.0 if distance_m else 0.0
            duration_min = duration_s / 60.0 if duration_s else 0.0

            print(f"  [{idx}] ID: {act_id}")
            print(f"      Name:      {act_name}")
            print(f"      Type:      {act_type}")
            print(f"      Distance:  {distance_km:.2f} km ({distance_m:.0f} m)")
            print(f"      Duration:  {duration_min:.1f} min ({duration_s:.0f} s)")
            print(f"      Elevation: {elevation_m:.0f} m")
            print(f"      Date:      {start_time}")
            print("  " + "-" * 45)

        print("\n[SUCCESS] Garmin Connect integration is verified and working!")
    except Exception as e:
        print(f"\n[FAIL] Error fetching activities from Garmin Connect: {e}")
        sys.exit(1)


if __name__ == "__main__":
    test_garmin_connection()
