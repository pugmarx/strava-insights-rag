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


def extract_time_filters(user_query):
    """
    Extract date/time filters from user query, supporting relative terms like
    'this year', 'last year', 'this month', 'last month', explicit years, and month names.
    Returns a list of SQL where condition strings.
    """
    import re
    now = datetime.now()
    query_lower = user_query.lower()
    conditions = []
    
    # 1. Year filters
    if 'this year' in query_lower:
        conditions.append(f"EXTRACT(YEAR FROM timestamp) = {now.year}")
    elif 'last year' in query_lower:
        conditions.append(f"EXTRACT(YEAR FROM timestamp) = {now.year - 1}")
    else:
        year_match = re.search(r'\b(20\d{2})\b', user_query)
        if year_match:
            conditions.append(f"EXTRACT(YEAR FROM timestamp) = {year_match.group(1)}")
            
    # 2. Month filters
    month_names = {
        'january': 1, 'jan': 1,
        'february': 2, 'feb': 2,
        'march': 3, 'mar': 3,
        'april': 4, 'apr': 4,
        'may': 5,
        'june': 6, 'jun': 6,
        'july': 7, 'jul': 7,
        'august': 8, 'aug': 8,
        'september': 9, 'sep': 9, 'sept': 9,
        'october': 10, 'oct': 10,
        'november': 11, 'nov': 11,
        'december': 12, 'dec': 12
    }
    
    if 'this month' in query_lower:
        if not any("EXTRACT(YEAR FROM timestamp)" in c for c in conditions):
            conditions.append(f"EXTRACT(YEAR FROM timestamp) = {now.year}")
        conditions.append(f"EXTRACT(MONTH FROM timestamp) = {now.month}")
    elif 'last month' in query_lower:
        last_month = 12 if now.month == 1 else now.month - 1
        last_month_year = now.year - 1 if now.month == 1 else now.year
        conditions = [c for c in conditions if "EXTRACT(YEAR FROM timestamp)" not in c]
        conditions.append(f"EXTRACT(YEAR FROM timestamp) = {last_month_year}")
        conditions.append(f"EXTRACT(MONTH FROM timestamp) = {last_month}")
    else:
        for m_name, m_num in month_names.items():
            if re.search(r'\b' + m_name + r'\b', query_lower):
                conditions.append(f"EXTRACT(MONTH FROM timestamp) = {m_num}")
                break

    # 3. Recent days/weeks
    if 'this week' in query_lower:
        conditions.append("timestamp >= DATE_TRUNC('week', CURRENT_DATE)")
    elif 'past 30 days' in query_lower or 'last 30 days' in query_lower:
        conditions.append("timestamp >= CURRENT_DATE - INTERVAL '30 days'")
    elif 'past 7 days' in query_lower or 'last 7 days' in query_lower:
        conditions.append("timestamp >= CURRENT_DATE - INTERVAL '7 days'")

    return conditions


def retrieve_similar_activities(user_query, top_k=5):
    """
    Smart RAG Retrieval: Handle different query types, multi-activity filters, and chronological listings.
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
        
        # 1. Collect all mentioned activity types (supports multi-activity queries like 'cycling and hiking')
        matched_types = []
        if 'run' in query_lower:
            matched_types.extend(['Run', 'TrailRun', 'VirtualRun'])
        if any(word in query_lower for word in ['ride', 'cycling', 'bike', 'cycl']):
            matched_types.extend(['Ride', 'VirtualRide', 'EBikeRide', 'GravelRide', 'MountainBikeRide'])
        if any(word in query_lower for word in ['hike', 'hiking', 'trek', 'walk', 'walking']):
            matched_types.extend(['Hike', 'Walk'])
        if any(word in query_lower for word in ['workout', 'workouts', 'weight', 'strength', 'gym', 'training']):
            matched_types.extend(['WeightTraining', 'Workout'])
        if any(word in query_lower for word in ['swim', 'swimming']):
            matched_types.extend(['Swim'])

        if matched_types:
            types_str = ", ".join(f"'{t}'" for t in set(matched_types))
            where_conditions.append(f"activity_type IN ({types_str})")
        
        # 2. Apply time filters (e.g. this year, this month, July, 2026, etc.)
        time_filters = extract_time_filters(user_query)
        where_conditions.extend(time_filters)
        
        # 3. Detect if query is a listing / timeline query
        is_listing_query = any(k in query_lower for k in ['list', 'show', 'all', 'activities in', 'history', 'log', 'what did i do', 'how many', 'summary', 'everything']) or bool(time_filters)
        
        # 4. Handle sorting logic
        if any(word in query_lower for word in ['longest', 'best', 'top', 'max', 'most']) and 'similar' not in query_lower:
            if any(word in query_lower for word in ['workout', 'workouts', 'weight', 'strength', 'gym', 'training']):
                order_by = "duration DESC"
            else:
                order_by = "distance DESC"
        elif 'fastest' in query_lower:
            where_conditions.append("distance > 1000")  # Only meaningful for actual activities
            order_by = "(distance/duration) DESC"
        elif 'recent' in query_lower or 'latest' in query_lower or is_listing_query:
            order_by = "timestamp DESC"
        elif 'shortest' in query_lower:
            order_by = "distance ASC"
        
        # For timeline/listing queries, retrieve enough items so the whole month/period is represented
        fetch_limit = max(top_k, 60) if is_listing_query else top_k
        
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
            final_params = params + [fetch_limit]
        else:
            final_params = [embedding_list] + [fetch_limit]
        
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
        return "No activities found."
    
    context_lines = []
    for i, activity in enumerate(retrieved_activities, 1):
        # Format timestamp
        if isinstance(activity['timestamp'], str):
            timestamp = datetime.fromisoformat(activity['timestamp'])
        else:
            timestamp = activity['timestamp']
        date_str = timestamp.strftime('%Y-%m-%d %H:%M') if timestamp else 'Unknown date'
        
        # Format distance
        distance_meters = activity.get('distance')
        if distance_meters:
            distance_km = distance_meters / 1000
            distance_str = f"{distance_km:.2f}km"
        else:
            distance_str = "N/A"
        
        # Format duration
        duration_sec = activity.get('duration', 0)
        hours = duration_sec // 3600
        minutes = (duration_sec % 3600) // 60
        seconds = duration_sec % 60
        if hours > 0:
            duration_str = f"{hours}h {minutes}m {seconds}s"
        else:
            duration_str = f"{minutes}m {seconds}s"
        
        # Calculate pace for running
        pace_str = ""
        if activity['activity_type'] in ['Run', 'TrailRun', 'VirtualRun'] and distance_meters and distance_meters > 0:
            pace_sec_per_km = duration_sec / (distance_meters / 1000)
            pace_min = int(pace_sec_per_km // 60)
            pace_sec = int(pace_sec_per_km % 60)
            pace_str = f", Pace: {pace_min}:{pace_sec:02d}/km"
        
        # Calculate speed for cycling
        speed_str = ""
        if activity['activity_type'] in ['Ride', 'VirtualRide', 'EBikeRide', 'GravelRide', 'MountainBikeRide'] and distance_meters and duration_sec > 0:
            speed_kmh = (distance_meters / 1000) / (duration_sec / 3600)
            speed_str = f", Speed: {speed_kmh:.1f}km/h"
        
        context_lines.append(
            f"{i}. {activity['activity_type']} on {date_str} (ID: {activity['activity_id']}) - "
            f"Distance: {distance_str}, Duration: {duration_str}{pace_str}{speed_str}"
        )
    
    return "\n".join(context_lines)

def generate_rag_response(user_query, context):
    """
    Generate final response using LLM with retrieved context and temporal grounding.
    """
    now = datetime.now()
    current_date_str = now.strftime('%B %d, %Y')
    current_year = now.year
    current_month = now.strftime('%B')

    prompt = f"""You are a helpful Strava activity assistant.
Today's Date: {current_date_str} (Current Year: {current_year}, Current Month: {current_month})

Retrieved Activity Context:
{context}

User Question: {user_query}

Instructions:
- Use the activity data provided above to answer the question
- When answering relative time queries (like 'this month', 'this year', 'last month'), refer to Today's Date ({current_date_str})
- ALWAYS state the specific activity type for each item (e.g. '- Ride on YYYY-MM-DD: ...', '- Hike on YYYY-MM-DD: ...', '- Run on YYYY-MM-DD: ...', '- Workout on YYYY-MM-DD: ...'). NEVER use the generic word 'Activity' when the specific type is known.
- Group activities by their activity type (e.g. Rides, Runs, Hikes, Workouts) if multiple types exist
- Enlist each qualifying activity as a clean unindented bullet point (- [Type] on YYYY-MM-DD: Distance, Duration, Speed/Pace)
- For WeightTraining and Workout activities, focus on duration as the main performance metric
- For running activities, pace (min/km) is often more meaningful than speed
- For cycling activities, consider both distance and speed
- Include dates, distances, and performance metrics in your analysis
- If comparing activities across time periods, highlight the differences
- Don't mention similarity scores or technical details about retrieval
- Keep formatting clean, factual, and concise without using emojis

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