from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def handle_redirect():
    """Capture Strava's OAuth redirect and extract the auth code."""
    auth_code = request.args.get("code")
    if auth_code:
        return f"Authorization Code: {auth_code}<br>Copy and use it to fetch your access token!"
    return "No authorization code found!", 400

if __name__ == "__main__":
    app.run(port=8080)
