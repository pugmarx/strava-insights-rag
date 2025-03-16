
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
