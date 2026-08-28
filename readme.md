# Strava Insights RAG

This started off as a hobby project to explore RAG and vector embeddings on Strava activity data. Whenever I get some time, I keep refining it.

For more technical notes, check out **[docs/overview.md](docs/overview.md)**.

---

## Architecture

```mermaid
flowchart LR
    User([User / Browser])
    Strava[Strava API / Webhooks]

    subgraph Backend ["Flask Backend"]
        API[API Endpoints]
        Embed[FastEmbed]
        RAG[RAG & SQL Pipeline]
        Sync[Strava Sync Service]
        LLM[LLM Client<br/>Ollama / Groq / Hugging Face]
    end

    subgraph Storage ["PostgreSQL + pgvector"]
        DB[(Activities & Vectors)]
        Tokens[(OAuth Tokens)]
    end

    User <-->|Queries & Dashboard| API
    Strava -->|Webhooks / Activity Data| Sync
    Sync <-->|OAuth / Refresh| Tokens
    Sync -->|Fetch Activity Details| Strava
    Sync --> Embed
    Embed -->|Store Embeddings| DB
    API --> RAG
    RAG --> Embed
    RAG <-->|Vector + SQL Filter| DB
    RAG --> LLM
    LLM --> RAG
```

---

## Key Interaction Flows

### 1. Asking a Question (RAG Pipeline)

When you ask a question like *"What was my longest run this month?"*, the app embeds the query, searches PostgreSQL with pgvector, and passes the relevant activities to the LLM to write the response.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant API as Flask Backend
    participant Embed as FastEmbed
    participant DB as Postgres (pgvector)
    participant LLM as LLM (Ollama / Groq / HF)

    User->>API: POST /query {"question": "What was the longest run in 2024?"}
    API->>Embed: Embed question text
    Embed-->>API: 384-d vector
    API->>DB: Cosine search (<=>) + SQL filters
    DB-->>API: Top matching activities
    API->>LLM: Prompt (Question + Retrieved Activities context)
    LLM-->>API: Grounded answer
    API-->>User: JSON response
```

### 2. Syncing Activities (Webhooks / On-Demand)

When a new workout finishes on Strava (or when you trigger a manual sync), the app pulls the activity metadata, creates an embedding, and stores it in Postgres.

```mermaid
sequenceDiagram
    autonumber
    actor Strava as Strava / User
    participant API as Flask Backend
    participant StravaAPI as Strava API
    participant Embed as FastEmbed
    participant DB as Postgres (pgvector)

    Strava->>API: Webhook event / POST /api/sync
    API->>StravaAPI: Fetch full activity details (with OAuth token)
    StravaAPI-->>API: Activity data (distance, duration, elevation, etc.)
    API->>Embed: Generate text summary & vector embedding
    Embed-->>API: Embedding vector
    API->>DB: Upsert activity record + vector
    DB-->>API: OK
```

---

## Prerequisites

```sh
brew install postgresql pgvector ollama
pip install -r requirements.txt
```

### Vector Similarity Metrics in pgvector

> Distance operators in pgvector return **lower values for more similar vectors**.

| Metric | Operator | Best For | Interpretation |
|---|---|---|---|
| **Cosine Distance** | `<=>` | Semantic / contextual similarity | **Lower = More similar** |
| **Euclidean (L2)** | `<->` | Geometric proximity | **Lower = More similar** |
| **Inner Product (neg.)** | `<#>` | Normalized vectors (dot product) | **Lower = More similar** *(negative inner product)* |

---

## Setup & Running

1. Copy `sample.env` to `.env` and fill in your credentials:
```properties
# Strava
STRAVA_USER_ID="YOUR_STRAVA_USER_ID"
STRAVA_CLIENT_ID="YOUR_STRAVA_CLIENT_ID"
STRAVA_CLIENT_SECRET="YOUR_STRAVA_CLIENT_SECRET"

# Database
POSTGRES_DB="stravadb"
POSTGRES_USER="strava_user"
POSTGRES_PASSWORD="YOUR_DB_PASSWORD"
POSTGRES_HOST="localhost"
POSTGRES_PORT="5432"

# LLM Provider (ollama, groq, or huggingface)
LLM_PROVIDER="ollama"
```

2. Start PostgreSQL and Ollama (if using local models):
```sh
brew services start postgresql@14
brew services start ollama
```

3. Run the backend:
```sh
python3 backend/app.py
```
The server will start at `http://localhost:5000`.

---

## Usage

Ask a question:
```sh
curl -X POST http://localhost:5000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What was the longest run in 2024?"}'
```

Trigger an on-demand sync:
```sh
curl -X POST http://localhost:5000/api/sync \
  -H "Content-Type: application/json" \
  -d '{"limit": 20}'
```