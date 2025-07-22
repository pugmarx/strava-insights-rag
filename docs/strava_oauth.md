## Strava OAuth


### Prequisite:
Get `client_id` and `client_secret` from 'My API Application' section of your Strava settings.

![API Application](img/api_app_strava.png)


### OAuth Flow
Strava OAuth is a bit unintuitive and takes some time to wrap your head around. Here's a high-level flow. This is represented in the following diagrams.

* First diagram: Shows the one-time manual OAuth setup process
* Second diagram: Shows the automated token refresh and API usage flow that happens every time you run your app

### First Time Authentication
```mermaid
sequenceDiagram
    actor You
    participant Browser
    participant StravaAuth as Strava OAuth Server
    participant App as User App

    You->>Browser: Visit Strava Auth URL with client_id
    Browser->>StravaAuth: Login + Authorize App
    StravaAuth-->>Browser: Redirect with Authorization Code
    Browser-->>You: Copy the auth code from URL

    You->>App: Paste auth code into app
    App->>StravaAuth: Exchange code for tokens
    StravaAuth-->>App: Returns access_token, refresh_token, expires_at
    App->>App: Save tokens to token.json
```

### Subsequent App Usage
```mermaid
sequenceDiagram
    participant App as User App
    participant StravaAuth as Strava OAuth Server
    participant StravaAPI as Strava API

    App->>App: Load token.json
    App->>App: Check if access_token expired

    alt Token still valid
        App->>StravaAPI: Use access_token to fetch activities
        StravaAPI-->>App: Return activity data
    else Token expired
        App->>StravaAuth: Send refresh_token
        StravaAuth-->>App: Return new access_token + refresh_token
        App->>App: Update token.json with new tokens
        App->>StravaAPI: Use new access_token to fetch activities
        StravaAPI-->>App: Return activity data
    end
```