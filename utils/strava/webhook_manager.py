import os
import sys
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
VERIFY_TOKEN = os.getenv("STRAVA_VERIFY_TOKEN", "STRAVA_INSIGHTS_WEBHOOK_VERIFY_TOKEN")
SUBSCRIPTION_URL = "https://www.strava.com/api/v3/push_subscriptions"


def view_subscription():
    """List active push subscription for this Strava application."""
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET in .env")
        return

    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    res = requests.get(SUBSCRIPTION_URL, params=params)
    if res.status_code == 200:
        subs = res.json()
        if subs:
            print("\n📋 Active Strava Push Subscription(s):")
            for sub in subs:
                print(f"  • ID: {sub.get('id')}")
                print(f"    Callback URL: {sub.get('callback_url')}")
                print(f"    Created: {sub.get('created_at')}")
                print(f"    Updated: {sub.get('updated_at')}")
        else:
            print("\nℹ️ No active Strava push subscriptions found.")
    else:
        print(f"Error viewing subscriptions ({res.status_code}): {res.text}")


def create_subscription(callback_url):
    """Register a new webhook callback URL with Strava."""
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET in .env")
        return

    if not callback_url.endswith("/strava/webhook"):
        callback_url = callback_url.rstrip("/") + "/strava/webhook"

    print(f"🔗 Registering Strava webhook with callback URL: {callback_url}")
    print(f"🔑 Using verify token: {VERIFY_TOKEN}")

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "callback_url": callback_url,
        "verify_token": VERIFY_TOKEN
    }

    res = requests.post(SUBSCRIPTION_URL, data=payload)
    if res.status_code in (200, 201):
        sub = res.json()
        print(f"\n🎉 Webhook subscription created successfully!")
        print(f"  • Subscription ID: {sub.get('id')}")
        print(f"  • Callback URL: {sub.get('callback_url')}")
    else:
        print(f"\n❌ Error creating subscription ({res.status_code}): {res.text}")
        print("Tip: Make sure your server is running and accessible at the callback URL before registering.")


def delete_subscription(sub_id):
    """Delete an active push subscription by ID."""
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET in .env")
        return

    url = f"{SUBSCRIPTION_URL}/{sub_id}"
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    res = requests.delete(url, params=params)
    if res.status_code in (200, 204):
        print(f"\n✅ Subscription {sub_id} deleted successfully.")
    else:
        print(f"\n❌ Error deleting subscription {sub_id} ({res.status_code}): {res.text}")


def main():
    parser = argparse.ArgumentParser(description="Manage Strava Webhook Push Subscriptions")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # view command
    subparsers.add_parser("view", help="View current active webhook subscription")

    # create command
    create_parser = subparsers.add_parser("create", help="Create a new webhook subscription")
    create_parser.add_argument("url", help="Base URL or full webhook URL (e.g., https://strava-insights-rag.onrender.com)")

    # delete command
    del_parser = subparsers.add_parser("delete", help="Delete a webhook subscription")
    del_parser.add_argument("id", help="Subscription ID to delete")

    args = parser.parse_args()

    if args.command == "view":
        view_subscription()
    elif args.command == "create":
        create_subscription(args.url)
    elif args.command == "delete":
        delete_subscription(args.id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
