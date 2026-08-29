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
        Cache[Tier 1: CacheManager<br/>In-Memory RAM]
        Embed[FastEmbed]
        RAG[RAG & SQL Pipeline]
        Sync[Strava Sync Service]
        LLM[LLM Client<br/>Ollama / Groq / Hugging Face]
    end

    subgraph Storage ["PostgreSQL + pgvector"]
        DB[(Activities & Vectors)]
        DBCache[(Tier 2: query_cache)]
        Tokens[(OAuth Tokens)]
    end

    User <-->|Queries & Dashboard| API
    API <-->|Exact Hits < 1ms| Cache
    API --> RAG
    RAG <-->|Semantic Cache Match >= 0.92| DBCache
    RAG --> Embed
    RAG <-->|Vector + SQL Filter| DB
    RAG --> LLM
    LLM --> RAG
    Strava -->|Webhooks / Activity Data| Sync
    Sync <-->|OAuth / Refresh| Tokens
    Sync -->|Fetch Activity Details| Strava
    Sync --> Embed
    Embed -->|Store Embeddings| DB
    Sync -->|Year-Scoped Invalidation| Cache
    Sync -->|Year-Scoped Invalidation| DBCache

```

---

## Key Interaction Flows

### 1. Asking a Question (Two-Tier Cached RAG Pipeline)

When a question is asked, the backend checks the in-memory cache, then checks PostgreSQL for semantically similar previous answers, and only calls the LLM if there is a cache miss.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant API as Flask Backend
    participant Cache as Tier 1 In-Memory
    participant DBCache as Tier 2 Postgres (query_cache)
    participant Embed as FastEmbed
    participant DB as Postgres (pgvector)
    participant LLM as LLM (Ollama / Groq / HF)

    User->>API: POST /query {"question": "What was the longest hike in October 2024?"}
    API->>Cache: Check exact in-memory match
    alt Tier 1 In-Memory Hit (sub-ms)
        Cache-->>API: Cached response
        API-->>User: JSON response
    else Tier 1 Miss
        API->>Embed: Compute query vector
        Embed-->>API: 384-d vector
        API->>DBCache: Cosine match (similarity >= 0.92)
        alt Tier 2 Semantic Hit (< 20ms)
            DBCache-->>API: Cached response
            API->>Cache: Populate Tier 1 RAM
            API-->>User: JSON response
        else Tier 2 Miss (Cold Path)
            API->>DB: Cosine search (<=>) + SQL filters
            DB-->>API: Matching activities context
            API->>LLM: Prompt (Question + Context)
            LLM-->>API: Grounded answer
            API->>Cache: Store in Tier 1 RAM
            API->>DBCache: Store in Tier 2 Postgres
            API-->>User: JSON response
        end
    end
```

### 2. Syncing Activities & Smart Cache Invalidation

When a new workout finishes on Strava (or when you trigger a manual sync), the app pulls the activity metadata, creates an embedding, stores it in Postgres, and invalidates only the affected year's cache.

```mermaid
sequenceDiagram
    autonumber
    actor Strava as Strava / User
    participant API as Flask Backend
    participant StravaAPI as Strava API
    participant Embed as FastEmbed
    participant DB as Postgres (pgvector)
    participant Cache as CacheManager (Tier 1 & Tier 2)

    Strava->>API: Webhook event / POST /api/sync
    API->>StravaAPI: Fetch full activity details (with OAuth token)
    StravaAPI-->>API: Activity data (e.g. 2026 workout)
    API->>Embed: Generate text summary & vector embedding
    Embed-->>API: Embedding vector
    API->>DB: Upsert activity record + vector
    API->>Cache: Invalidate affected year (2026) & relative queries
    Cache->>Cache: Clear in-memory query & analytics cache
    Cache->>DB: DELETE FROM query_cache WHERE target_year = 2026 OR NULL
    Note over Cache,DB: Historical queries (2021-2025) remain 100% cached!
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