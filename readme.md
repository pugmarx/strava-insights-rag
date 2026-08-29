# Strava Insights RAG

This started off as a hobby project to explore RAG and vector embeddings on Strava activity data. Whenever I get some time, I keep refining it.

For more technical notes, check out **[docs/overview.md](docs/overview.md)**.

---

## Architecture

```mermaid
%%{init: {'flowchart': {'curve': 'basis'}}}%%
flowchart LR
    User([User / Browser])
    Strava[Strava API / Webhooks]

    subgraph Backend ["Flask Backend"]
        API[API Endpoints]
        Cache[Cache Manager<br/>RAM + DB]
        RAG[RAG & Analytics Engine]
        Sync[Strava Sync Service]
        LLM[LLM Client<br/>Ollama / Groq / Hugging Face]
    end

    subgraph Storage ["PostgreSQL + pgvector"]
        DB[(Activities & Embeddings)]
        DBCache[(Query Cache)]
        Tokens[(OAuth Tokens)]
    end

    User <-->|Queries & Dashboard| API
    API <--> Cache
    API --> RAG
    RAG <--> DB
    RAG <--> DBCache
    RAG <--> LLM
    Strava -->|Webhooks / Activities| Sync
    Sync <--> Tokens
    Sync --> DB
    Sync -.->|Invalidate| Cache
```

---

## Key Interaction Flows

### 1. Asking a Question (Two-Tier Cached RAG)

When a question is asked, the backend checks the in-memory cache, then checks PostgreSQL for semantically similar previous answers ($\ge 0.92$), and only calls the LLM if there is a cache miss.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant API as Flask Backend
    participant Cache as Tier 1 In-Memory
    participant DBCache as Tier 2 Postgres (query_cache)
    participant DB as Postgres (pgvector)
    participant LLM as LLM (Ollama / Groq / HF)

    User->>API: POST /query {"question": "What was the longest hike in October 2024?"}
    API->>Cache: Check exact in-memory match
    alt Tier 1 Hit (< 1ms)
        Cache-->>API: Cached response
        API-->>User: JSON response
    else Tier 1 Miss
        API->>DBCache: Cosine match (similarity >= 0.92)
        alt Tier 2 Semantic Hit (< 20ms)
            DBCache-->>API: Cached response
            API->>Cache: Populate Tier 1 RAM
            API-->>User: JSON response
        else Tier 2 Miss (Cold Path)
            API->>DB: Search matching activities
            DB-->>API: Activity context
            API->>LLM: Prompt (Question + Context)
            LLM-->>API: Grounded answer
            API->>Cache: Save to Tier 1 RAM
            API->>DBCache: Save to Tier 2 Postgres
            API-->>User: JSON response
        end
    end
```

### 2. Syncing Activities (Webhooks / On-Demand)

When a new workout finishes on Strava (or when you trigger a manual sync), the app fetches details, generates embeddings, stores them in Postgres, and triggers cache invalidation.

```mermaid
sequenceDiagram
    autonumber
    actor Strava as Strava / User
    participant API as Flask Backend
    participant StravaAPI as Strava API
    participant DB as Postgres (pgvector)
    participant Cache as Cache Manager

    Strava->>API: Webhook event / POST /api/sync
    API->>StravaAPI: Fetch activity details (OAuth)
    StravaAPI-->>API: Activity data (distance, elevation, duration)
    API->>DB: Upsert activity record & embedding
    API->>Cache: Invalidate cache for affected year
    Cache->>DB: Clear affected year & relative query entries
    DB-->>API: OK
```

### 3. Year-Based Cache Invalidation

Past closed years are immutable and remain permanently cached. Only the affected activity's year and relative queries are cleared when new workouts arrive:

```mermaid
%%{init: {'flowchart': {'curve': 'basis'}}}%%
flowchart TD
    NewAct["New Activity Synced (e.g. Year 2026)"]
    
    NewAct --> Clear["Invalidated:<br/>• Queries for 2026 (target_year = 2026)<br/>• Relative/all-time queries (target_year IS NULL)<br/>• Dashboard analytics totals"]
    NewAct -.-> Keep["Preserved (100% Cached):<br/>• All past closed years (e.g. 2016 - 2025)"]
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