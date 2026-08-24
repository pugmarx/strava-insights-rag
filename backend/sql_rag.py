import requests
import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
from fastembed import TextEmbedding
from db_pool import get_pool
from llm_client import LLMClient

# Load environment variables
load_dotenv()

# Read database credentials
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_SSLMODE = os.getenv("POSTGRES_SSLMODE", "prefer")

# Initialize LLM Client (Hugging Face / Groq / Ollama)
llm_client = LLMClient()

# Initialize fastembed model (low memory, ONNX runtime)
model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

def compute_embedding(text):
    """Generate vector embedding as a Python list using fastembed."""
    emb = list(model.embed([text]))[0]
    return emb.tolist() if hasattr(emb, "tolist") else list(emb)

def connect_db():
    """Establish a connection to PostgreSQL database using connection pool or direct fallback."""
    pool = get_pool()
    if pool:
        try:
            return pool.getconn()
        except Exception:
            pass
    try:
        conn = psycopg2.connect(
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            sslmode=POSTGRES_SSLMODE
        )
        return conn
    except psycopg2.Error as e:
        print(f"Database connection error: {e}")
        return None

def efficient_retrieve_activities(user_query, top_k=5, debug=False):
    """
    More efficient retrieval that uses SQL for clear superlative queries,
    vector search for semantic queries.
    """
    query_lower = user_query.lower()
    
    # For very clear superlative queries, skip embeddings entirely
    clear_superlatives = {
        'longest run': "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type = 'Run' ORDER BY distance DESC",
        'fastest run': "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type = 'Run' AND distance > 1000 ORDER BY (distance/duration) DESC",
        'longest ride': "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type = 'Ride' ORDER BY distance DESC",
        'recent runs': "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type = 'Run' ORDER BY timestamp DESC",
        'recent workouts': "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type IN ('WeightTraining', 'Workout') AND (distance IS NULL OR distance < 1000) ORDER BY timestamp DESC",
        'longest workout': "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type IN ('WeightTraining', 'Workout') AND (distance IS NULL OR distance < 1000) ORDER BY duration DESC",
        'best workouts': "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type IN ('WeightTraining', 'Workout') AND (distance IS NULL OR distance < 1000) ORDER BY duration DESC",
    }
    
    # Check for exact matches to skip vector computation
    for phrase, sql_base in clear_superlatives.items():
        if phrase in query_lower:
            if debug:
                print(f"> DEBUG: Using optimized SQL for '{phrase}' query")
            return execute_direct_sql(sql_base, top_k, debug)
    
    # For "best" queries, determine context
    if 'best' in query_lower:
        if 'run' in query_lower:
            if 'pace' in query_lower or 'time' in query_lower:
                sql = "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type = 'Run' AND distance > 1000 ORDER BY (distance/duration) DESC"
            else:
                sql = "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type = 'Run' ORDER BY distance DESC"
            if debug:
                print(f"> DEBUG: Using optimized SQL for 'best run' query")
            return execute_direct_sql(sql, top_k, debug)
        elif any(word in query_lower for word in ['workout', 'weight', 'strength', 'gym', 'training']):
            sql = "SELECT activity_id, activity_type, distance, duration, timestamp, 1.0 as similarity_score FROM activities WHERE activity_type IN ('WeightTraining', 'Workout') AND (distance IS NULL OR distance < 1000) ORDER BY duration DESC"
            if debug:
                print(f"> DEBUG: Using optimized SQL for 'best workout' query")
            return execute_direct_sql(sql, top_k, debug)
    
    # Fall back to vector similarity for complex/semantic queries
    if debug:
        print(f"> DEBUG: Using vector similarity search for complex query")
    return retrieve_similar_activities(user_query, top_k)

def execute_direct_sql(sql_query, limit, debug=False):
    """
    Execute direct SQL without vector computation for efficiency.
    """
    conn = connect_db()
    if not conn:
        return []
    
    cursor = conn.cursor()
    
    try:
        full_query = f"{sql_query} LIMIT {limit}"
        if debug:
            print(f"> DEBUG: Executing optimized query: {full_query}")
        
        cursor.execute(full_query)
        results = cursor.fetchall()
        
        # Convert to same format as vector search results
        activities = []
        for row in results:
            activities.append({
                'activity_id': row[0],
                'activity_type': row[1], 
                'distance': row[2],
                'duration': row[3],
                'timestamp': row[4],
                'similarity_score': row[5]  # Set to 1.0 for direct matches
            })
        
        if debug:
            print(f"> DEBUG: Direct SQL returned {len(activities)} activities")
        
        return activities
        
    except psycopg2.Error as e:
        if debug:
            print(f"> DEBUG: Error in direct SQL: {e}")
        return []
    finally:
        cursor.close()
        conn.close()


    """
    RAG Retrieval Step: Find activities similar to user query using vector similarity.
    Enhanced to handle superlative queries (longest, fastest, etc.)
    """
    # Convert user query to embedding
    query_embedding = compute_embedding(user_query)
    
    # Check if this is a superlative query that needs special handling
    superlative_keywords = {
        'longest': ('distance', 'DESC'),
        'shortest': ('distance', 'ASC'), 
        'fastest': ('duration', 'ASC'),  # assuming faster = less time
        'slowest': ('duration', 'DESC'),
        'recent': ('timestamp', 'DESC'),
        'oldest': ('timestamp', 'ASC')
    }
    
    # Handle "best" with context-aware logic
    best_keywords = ['best', 'top', 'greatest', 'personal record', 'pr']
    
    # Check if query contains superlative words
    query_lower = user_query.lower()
    sort_column = None
    sort_order = None
    is_best_query = False
    
    # Check for "best" queries first
    if any(keyword in query_lower for keyword in best_keywords):
        is_best_query = True
        # Determine what "best" means based on context
        if 'run' in query_lower:
            if 'pace' in query_lower or 'fast' in query_lower:
                # Best pace = shortest duration for similar distances
                sort_column = 'pace'  # Special handling below
            else:
                # Default "best run" = longest distance
                sort_column = 'distance'
                sort_order = 'DESC'
        elif 'ride' in query_lower or 'cycling' in query_lower:
            # Best ride = longest distance
            sort_column = 'distance' 
            sort_order = 'DESC'
        elif any(word in query_lower for word in ['workout', 'weight', 'strength', 'gym', 'training']):
            # Best workout = longest duration (most time spent training)
            sort_column = 'duration'
            sort_order = 'DESC'
        else:
            # Generic "best" = longest distance across all activities
            sort_column = 'distance'
            sort_order = 'DESC'
    else:
        # Regular superlative keywords
        for keyword, (column, order) in superlative_keywords.items():
            if keyword in query_lower:
                sort_column = column
                sort_order = order
                break
    
    conn = connect_db()
    if not conn:
        return []
    
    cursor = conn.cursor()
    
    try:
        if sort_column:
            # For superlative queries, get top activities by the relevant metric
            # Filter by activity type FIRST, then sort (more efficient)
            activity_type_filter = ""
            filter_params = [query_embedding]
            
            if 'run' in query_lower:
                activity_type_filter = "WHERE activity_type = 'Run'"
            elif 'ride' in query_lower or 'cycling' in query_lower or 'bike' in query_lower:
                activity_type_filter = "WHERE activity_type = 'Ride'"
            elif 'hike' in query_lower:
                activity_type_filter = "WHERE activity_type = 'Hike'"
            elif any(word in query_lower for word in ['workout', 'weight', 'strength', 'gym', 'training']):
                activity_type_filter = "WHERE activity_type IN ('WeightTraining', 'Workout') AND (distance IS NULL OR distance < 1000)"
            
            # Special handling for pace-based "best" queries
            if sort_column == 'pace':
                # Best pace = fastest speed (distance/duration) for runs > 1km
                additional_filter = " AND distance > 1000" if activity_type_filter else "WHERE distance > 1000"
                cursor.execute(f"""
                    SELECT activity_id, activity_type, distance, duration, timestamp,
                           1 - (embedding <=> %s::vector) as similarity_score,
                           (distance/1000.0)/(duration/3600.0) as pace_kmh
                    FROM activities 
                    {activity_type_filter}{additional_filter}
                    ORDER BY pace_kmh DESC
                    LIMIT %s
                """, (filter_params[0], top_k))
            else:
                cursor.execute(f"""
                    SELECT activity_id, activity_type, distance, duration, timestamp,
                           1 - (embedding <=> %s::vector) as similarity_score
                    FROM activities 
                    {activity_type_filter}
                    ORDER BY {sort_column} {sort_order}
                    LIMIT %s
                """, (filter_params[0], top_k))
        else:
            # Regular vector similarity search
            cursor.execute("""
                SELECT activity_id, activity_type, distance, duration, timestamp,
                       1 - (embedding <=> %s::vector) as similarity_score
                FROM activities 
                ORDER BY embedding <=> %s::vector 
                LIMIT %s
            """, (query_embedding, query_embedding, top_k))
        
        results = cursor.fetchall()
        
        # Convert to list of dictionaries
        activities = []
        for row in results:
            activities.append({
                'activity_id': row[0],
                'activity_type': row[1],
                'distance': row[2],
                'duration': row[3],
                'timestamp': row[4],
                'similarity_score': row[5]
            })
        
        return activities
        
    except psycopg2.Error as e:
        print(f"Error in vector search: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

def retrieve_similar_activities(user_query, top_k=5):
    """
    Smart RAG Retrieval: Handle different query types appropriately.
    """
    query_embedding = compute_embedding(user_query)
    query_lower = user_query.lower()
    
    conn = connect_db()
    if not conn:
        return []
    
    cursor = conn.cursor()
    
    try:
        embedding_list = query_embedding
        
        # Detect query patterns and build appropriate SQL
        base_select = """
            SELECT activity_id, activity_type, distance, duration, timestamp,
                   1 - (embedding <=> %s::vector) as similarity_score
            FROM activities
        """
        
        where_conditions = []
        order_by = "embedding <=> %s::vector"
        params = [embedding_list, embedding_list]
        
        # Filter by activity type if mentioned
        if 'run' in query_lower and 'running' not in query_lower:
            where_conditions.append("activity_type = 'Run'")
        elif any(word in query_lower for word in ['ride', 'cycling', 'bike']):
            where_conditions.append("activity_type = 'Ride'")
        elif any(word in query_lower for word in ['hike', 'hiking', 'trek']):
            where_conditions.append("activity_type = 'Hike'")
        elif any(word in query_lower for word in ['workout', 'workouts', 'weight', 'strength', 'gym', 'training']):
            where_conditions.append("activity_type IN ('WeightTraining', 'Workout') AND (distance IS NULL OR distance < 1000)")
        
        # Filter by year if mentioned
        import re
        year_match = re.search(r'(20\d{2})', user_query)
        if year_match:
            year = year_match.group(1)
            where_conditions.append(f"EXTRACT(YEAR FROM timestamp) = {year}")
        
        # Handle superlative queries
        if any(word in query_lower for word in ['longest', 'best', 'top']) and 'similar' not in query_lower:
            # For workout queries, use duration; for others use distance
            if any(word in query_lower for word in ['workout', 'workouts', 'weight', 'strength', 'gym', 'training']):
                order_by = "duration DESC"
            else:
                order_by = "distance DESC"
        elif 'fastest' in query_lower:
            where_conditions.append("distance > 1000")  # Only meaningful for actual activities
            order_by = "(distance/duration) DESC"
        elif 'recent' in query_lower:
            order_by = "timestamp DESC"
        elif 'shortest' in query_lower:
            order_by = "distance ASC"
        
        # Build final query
        where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        final_query = f"""
            {base_select}
            {where_clause}
            ORDER BY {order_by}
            LIMIT %s
        """
        
        # Adjust params based on order_by
        if order_by == "embedding <=> %s::vector":
            final_params = params + [top_k]
        else:
            final_params = [embedding_list] + [top_k]
        
        cursor.execute(final_query, final_params)
        results = cursor.fetchall()
        
        # Convert to list of dictionaries
        activities = []
        for row in results:
            activities.append({
                'activity_id': row[0],
                'activity_type': row[1],
                'distance': row[2],
                'duration': row[3],
                'timestamp': row[4],
                'similarity_score': row[5]
            })
        
        return activities
        
    except psycopg2.Error as e:
        print(f"Error in vector search: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

def build_context(retrieved_activities):
    """
    Build context string from retrieved activities for LLM with calculated metrics.
    """
    if not retrieved_activities:
        return "No relevant activities found."
    
    context = "Here are your most relevant activities:\n\n"
    
    for i, activity in enumerate(retrieved_activities, 1):
        # Format timestamp
        if isinstance(activity['timestamp'], str):
            timestamp = datetime.fromisoformat(activity['timestamp'])
        else:
            timestamp = activity['timestamp']
        
        # Calculate metrics
        distance_km = activity['distance'] / 1000 if activity['distance'] else 0
        duration_seconds = activity['duration'] if activity['duration'] else 0
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        
        # Calculate pace and speed
        pace_info = ""
        if distance_km > 0 and duration_seconds > 0:
            # Speed in km/h
            speed_kmh = distance_km / (duration_seconds / 3600)
            
            # Pace in min/km (common for running)
            pace_min_per_km = duration_seconds / 60 / distance_km
            pace_mins = int(pace_min_per_km)
            pace_secs = int((pace_min_per_km - pace_mins) * 60)
            
            pace_info = f", Speed: {speed_kmh:.1f} km/h, Pace: {pace_mins}:{pace_secs:02d} min/km"
        
        context += f"{i}. {activity['activity_type']} on {timestamp.strftime('%Y-%m-%d')}\n"
        context += f"   Distance: {distance_km:.1f} km, Duration: {hours}h {minutes}m{pace_info}\n"
        context += f"   Activity ID: {activity['activity_id']}\n"
        
        # Only show similarity score in debug mode or for semantic searches
        if activity['similarity_score'] < 0.9:  # Only show if it's actually a similarity search
            context += f"   Similarity: {activity['similarity_score']:.3f}\n"
        context += "\n"
    
    return context

def generate_rag_response(user_query, context):
    """
    RAG Generation Step: Use LLM to generate response based on retrieved context.
    """
    prompt = f"""You assistant which summarizes Strava activity data, based on the retrieved activity information below.

Retrieved Activity Context:
{context}

User Question: {user_query}

Instructions:
- Use the activity data provided above to answer the question
- ALWAYS use the exact activity_type shown in the data (WeightTraining, Workout, Run, Ride, etc.)
- For WeightTraining and Workout activities, focus on duration as the main performance metric
- For running activities, pace (min/km) is often more meaningful than speed
- For cycling activities, consider both distance and speed
- Include dates, distances, and performance metrics in your analysis
- If comparing activities across time periods, highlight the differences
- Don't mention similarity scores or technical details about retrieval
- Enlist the qualifying activities as bullets and prefix 'Ride' or 'Run' or 'Hike', according to the activity

Response:"""
    
    return llm_client.generate(prompt)

def handle_rag_query(user_query, debug=False):
    """
    Simple RAG pipeline: Retrieve → Augment → Generate
    Let the LLM interpret what "best" means from the retrieved context.
    """
    if debug:
        print(f"\n> DEBUG: Processing query: {user_query}")
    
    # Step 1: Simple vector similarity retrieval
    if debug:
        print("> DEBUG: Retrieving similar activities...")
    retrieved_activities = retrieve_similar_activities(user_query, top_k=15)  # Get more for LLM to choose from
    
    if not retrieved_activities:
        return "I couldn't find any relevant activities to answer your question."
    
    if debug:
        print(f"> DEBUG: Retrieved {len(retrieved_activities)} activities")
        print("> DEBUG: Top retrieved activities:")
        for i, activity in enumerate(retrieved_activities[:5], 1):
            distance_km = activity['distance'] / 1000 if activity['distance'] else 0
            timestamp = activity['timestamp']
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            print(f"   {i}. {activity['activity_type']}: {distance_km:.1f}km on {timestamp.strftime('%Y-%m-%d')} (similarity: {activity['similarity_score']:.3f})")
        
        # Show database stats
        # debug_all_activities()
    
    # Step 2: Build context from retrieved activities
    if debug:
        print("> DEBUG: Building context...")
    context = build_context(retrieved_activities)
    
    # Step 3: Generate response using LLM with context
    if debug:
        print("> DEBUG: Generating response...")
    response = generate_rag_response(user_query, context)
    
    return response

# Alternative: Hybrid approach (RAG + some SQL when needed)
def hybrid_query_handler(user_query):
    """
    Hybrid approach: Use RAG for most queries, but fall back to SQL for specific aggregations.
    """
    # Keywords that suggest aggregation queries that might need SQL
    sql_keywords = ['total', 'average', 'count', 'sum', 'most', 'least', 'fastest', 'slowest']
    
    if any(keyword in user_query.lower() for keyword in sql_keywords):
        print("Detected aggregation query, using hybrid approach...")
        
        # Get relevant activities via vector search
        retrieved_activities = retrieve_similar_activities(user_query, top_k=10)
        context = build_context(retrieved_activities)
        
        # Generate response that might include summary statistics
        enhanced_prompt = f"""Based on the retrieved activities and the user's question, provide a comprehensive response. If the question asks for totals, averages, or statistics, calculate them from the provided data.

Retrieved Activities:
{context}

User Question: {user_query}

Provide a helpful response with calculations if needed:"""
        
        return generate_rag_response(user_query, enhanced_prompt)
    else:
        # Use standard RAG for descriptive queries
        return handle_rag_query(user_query)

def debug_all_activities():
    """
    Debug function to show statistics about all activities in the database.
    """
    conn = connect_db()
    if not conn:
        print("> DEBUG: Could not connect to database")
        return
    
    cursor = conn.cursor()
    
    try:
        print("\n> DEBUG: Querying database statistics...")
        
        # Get total count by activity type
        cursor.execute("""
            SELECT activity_type, COUNT(*) as count, 
                   MIN(distance/1000) as min_km, MAX(distance/1000) as max_km,
                   AVG(distance/1000) as avg_km
            FROM activities 
            GROUP BY activity_type 
            ORDER BY count DESC
        """)
        
        stats = cursor.fetchall()
        print("\n> DEBUG: Database Activity Statistics:")
        print("   Type      | Count | Min(km) | Max(km) | Avg(km)")
        print("   ----------|-------|---------|---------|--------")
        for row in stats:
            print(f"   {row[0]:<9} | {row[1]:<5} | {row[2]:<7.1f} | {row[3]:<7.1f} | {row[4]:<7.1f}")
        
        # Get longest run specifically
        cursor.execute("""
            SELECT activity_id, distance/1000 as distance_km, timestamp
            FROM activities 
            WHERE activity_type = 'Run' 
            ORDER BY distance DESC 
            LIMIT 5
        """)
        
        longest_runs = cursor.fetchall()
        print(f"\n> DEBUG: Top 5 Longest Runs in Database:")
        for i, run in enumerate(longest_runs, 1):
            print(f"   {i}. {run[1]:.2f}km on {run[2]} (ID: {run[0]})")
            
        # Check total number of activities
        cursor.execute("SELECT COUNT(*) FROM activities")
        total_count = cursor.fetchone()[0]
        print(f"\n> DEBUG: Total activities in database: {total_count}")
            
    except psycopg2.Error as e:
        print(f"> DEBUG: Error getting stats: {e}")
    finally:
        cursor.close()
        conn.close()

# # Test the RAG system
# test_queries = [
#     "What are my best rides in 2022?",
#     # "Show me activities similar to my morning runs",
#     # "How did my cycling improve over time?"
# ]

# for query in test_queries:
#     print(f"\n{'='*50}")
#     print(f"Query: {query}")
#     print(f"{'='*50}")
#     response = handle_rag_query(query, debug=True)
#     print(response)