
## Strava-API-AI


### Prerequisites

```
brew install postgresql pgvector ollama
pip install fastapi uvicorn psycopg2-binary coremltools sentence-transformers pgvector
```


### Comparison Summary
| Function | Operator | Best For  | Interpretation  |
|-----------------|-----------------|-----------------|-----------------|
| Cosine Similarity   | <=> | Contextual similarity  | Higher = More similar  |
| L2 Distance	| <-> |	Geometric proximity |	Lower = More similar |
| Inner Product | <#> |	Pre-normalized vectors | Higher = More similar |



### Execution
1. Create `backend/.env` with:
```properties
# Strava
USER_ID = "xxx"
CLIENT_ID = "xxx"
CLIENT_SECRET = "xxxx"

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