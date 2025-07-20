# A Simple LLM Overview

**Process Strava activity data** – Store it in a structured format (PostgreSQL database).  
**Embed key details** – Using pgvector or another vector-based approach to enable semantic search.  
**Run queries using the LLM** – Convert user queries into structured filters and generate insights.

## I. GET DATA

### 1. Strava
- Social network for athletes
- Developer API available
- Register APP to get API credentials
- Fetch activities using REST endpoints

## II. ENCODE DATA

### 2. What are embeddings
These are numeric (vectorized) representations of text, allowing for semantic comparison (using MATH!), rather than keyword (text-based) comparison!

Suppose we have this activity:
```javascript
activity = {
  "name": "Morning Ride",
  "type": "Ride", 
  "distance": 24000, // meters
  "elapsed_time": 3600 // seconds
}
```

**Step 1: Textual Summary**
```
text = "Morning Ride Ride 24000 meters in 3600 seconds"
```

**Step 2: Embeddings (model used: sentence-transformer)**
Create a 384 dimensional vector, like so:
```
[0.01, -0.12, 0.33, ..., 0.08]
```
This vector is stored along with the data in DB.

### Example:
Suppose we embed these two texts:
- `"Evening Run 5km in 30 minutes"`
- `"Morning Jog 5000 meters in 1800 seconds"`

Even though the words are different, their meanings are similar (same activity, similar effort), so their vectors will be close together in the embedding space.

Whereas:
- `"Evening Ride 40km in 2 hours"`

Would be farther away — different activity type and effort.

## III. QUERY DATA

### 3. How are queries served:
Consider this example:

**User asks:**
> "Show me activities similar to my longest ride"

We do the following:
- Find the longest ride (e.g., "Morning Ride")
- Use its embedding vector as the reference
- Run a cosine similarity search in SQL:

```sql
SELECT *
FROM activities
ORDER BY embedding <=> '[0.01, -0.12, 0.33, ..., 0.08]'
LIMIT 5;
```

## IV. PROMPT ENGINEERING/REFINEMENT

### 4. Query Understanding & Context Building
- **Natural Language Processing**: Parse user queries to understand intent (find, compare, analyze, recommend)
- **Context Extraction**: Extract key parameters from queries (activity type, date ranges, performance metrics)
- **Query Classification**: Categorize queries into types:
  - Similarity searches ("activities like my best run")
  - Performance analysis ("how am I improving in cycling")
  - Temporal queries ("activities from last month")
  - Comparative queries ("compare my runs vs rides")

### 5. Response Generation
- **Structured Prompts**: Create templates for different query types
- **Data Integration**: Combine vector search results with structured data filters
- **Context-Aware Responses**: Include relevant statistics, trends, and insights
- **Follow-up Suggestions**: Propose related queries or deeper analysis

**Example Prompt Template:**
```
Based on the user's Strava data, analyze the following activities:
[ACTIVITY_DATA]

User Query: "{user_query}"
Similar Activities Found: {similarity_results}
Performance Metrics: {stats}

Provide insights focusing on:
1. Direct answer to the user's question
2. Notable patterns or trends
3. Actionable recommendations
4. Related activities they might find interesting
```

## V. APP-IFYING

### 6. Frontend Interface
- **Chat Interface**: Natural language query input with conversation history
- **Activity Visualization**: Interactive charts and maps for activity data
- **Filter Controls**: Quick filters for activity type, date range, and performance metrics
- **Recommendation Cards**: Suggested queries and insights based on user patterns

### 7. Backend Architecture
- **API Layer**: RESTful endpoints for data retrieval and query processing
- **Authentication**: Strava OAuth integration for secure data access
- **Caching Strategy**: Redis for frequently accessed embeddings and query results
- **Background Jobs**: Periodic data sync and embedding updates

### 8. Deployment & Scaling
- **Database**: PostgreSQL with pgvector extension for vector operations
- **Application Server**: Node.js/Python with embedding model integration
- **Monitoring**: Activity sync status, query performance, and user engagement metrics
- **Data Privacy**: Secure handling of personal fitness data with user consent

### 9. User Experience Flow
1. **Onboarding**: Connect Strava account and initial data sync
2. **Query Interface**: Natural language input with auto-suggestions
3. **Results Display**: Combined visual and textual insights
4. **Exploration**: Deep-dive into specific activities or trends
5. **Personalization**: Learn user preferences for better recommendations