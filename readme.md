## Strava-API-AI
This started off as a hobby project for me to understand RAG, using basic embeddings. Whenever I can make time, I keep refining it.

**[A more technical overview](docs/overview.md)**

### Prerequisites

```
brew install postgresql pgvector ollama
pip install fastapi uvicorn psycopg2-binary coremltools sentence-transformers pgvector
```


### Vector Similarity Metrics in pgvector

> All distance operators in pgvector return **lower values for more similar vectors**.

| Metric                  | Operator | Best For                     | Interpretation             |
|-------------------------|----------|-------------------------------|----------------------------|
| **Cosine Distance**     | `<=>`    | Semantic/contextual similarity | **Lower = More similar**   |
| **Euclidean (L2)**      | `<->`    | Geometric proximity            | **Lower = More similar**   |
| **Inner Product (neg.)**| `<#>`    | Normalized vectors (dot product) | **Lower = More similar** *(negative inner product)* |

### Notes:
- `<=>` is commonly used with **cosine distance**, depending on your index setup.
- If you want **similarity**, you can compute `1 - distance`.
- Ensure your vector column is indexed appropriately (`USING ivfflat WITH (distance_metric = 'cosine')`, etc).


### Execution
1. Create `backend/.env` with:
```properties
# Strava
STRAVA_USER_ID = "xxx"
STRAVA_CLIENT_ID = "xxx"
STRAVA_CLIENT_SECRET = "xxxx"

# Database
POSTGRES_DB="stravadb"
POSTGRES_USER="strava_user"
POSTGRES_PASSWORD="strava"
POSTGRES_HOST="localhost"
POSTGRES_PORT= "5432"
```
2. Ensure PGSQL DB is up (assuming that the schema is in place):
```sh
brew services start postgresql@14
```
3. Ensure Ollama is up:
```sh
brew services start ollama
``` 
4. Run backend/app.py
```sh
python3 app.py
```
This will start the FAST API server at: `:5000`

---
## Usage
Once the server is up, queries can be fired like:
```sh
curl -X POST http://localhost:5000/query -H "Content-Type: application/json" -d '{           
    "question": "What was my longest run?"         
}'
```