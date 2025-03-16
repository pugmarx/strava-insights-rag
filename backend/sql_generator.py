import requests
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Read database credentials
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")

# Ollama API details
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "mistral"  # Ensure Mistral is installed in Ollama

# Database connection
def connect_db():
    """Establish a connection to PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT
        )
        return conn
    except psycopg2.Error as e:
        print(f"Database connection error: {e}")
        return None

# Ollama Query Function
def query_ollama(prompt):
    """Send a query to the local Ollama LLM and return the response."""
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        return response.json().get("response", "No response received")
    except requests.exceptions.RequestException as e:
        return f"Error querying Ollama: {e}"

# Generate SQL Query using LLM
def generate_sql_query(user_question):
    """Send the user question to Ollama and get an SQL query back."""
    schema_info = """
    You are a PostgreSQL SQL expert using pgvector. Convert the user query into an SQL statement.
    
    ## Database Schema
    CREATE TABLE activities (
        activity_id BIGINT PRIMARY KEY,
        activity_type VARCHAR(50),
        distance DOUBLE PRECISION,
        duration INTEGER,
        timestamp TIMESTAMP,
        embedding VECTOR(384)
    );
    
    ## Query Rules:
    - Use `timestamp` for time-based queries.
    - Use `distance` and `duration` for activity performance queries.
    - Use `embedding <=> embedding` for cosine similarity queries.
    - Always return `activity_id`, `activity_type`, `distance`, `duration`, and `timestamp` in the SELECT statement.
    
    ## **Examples**
    ### Example 1: Find my longest run
    User Question: "What was my longest run?"
    SQL Query:
    SELECT activity_id, activity_type, distance, duration, timestamp 
    FROM activities 
    WHERE activity_type = 'Run' 
    ORDER BY distance DESC 
    LIMIT 1;
    
    ### Example 2: Find similar activities to my last run
    User Question: "Find similar activities to my last 'Run' activity"
    SQL Query:
    WITH last_run AS (
        SELECT embedding FROM activities 
        WHERE activity_type = 'Run' 
        ORDER BY timestamp DESC 
        LIMIT 1
    )
    SELECT activity_id, activity_type, distance, duration, timestamp, 
           1 - (embedding <=> (SELECT embedding FROM last_run)) AS similarity_score
    FROM activities
    ORDER BY similarity_score DESC
    LIMIT 5;
    
    ### Example 3: Find my most active month
    User Question: "Which month was I most active?"
    SQL Query:
    SELECT DATE_TRUNC('month', timestamp) AS activity_month, 
           COUNT(*) AS total_activities 
    FROM activities 
    GROUP BY activity_month 
    ORDER BY total_activities DESC 
    LIMIT 1;
    
    Now, generate the SQL query based on the following user question:
    User Question: {user_question}
    SQL Query:
    """
    
    full_prompt = schema_info.format(user_question=user_question)
    sql_query = query_ollama(full_prompt)
    
    # Clean response (removes markdown formatting, if any)
    sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
    
    # Debugging: Print SQL query for review
    print("\n* Generated SQL Query: *\n", sql_query)
    
    return sql_query

# Execute SQL Query
def execute_sql_query(sql_query):
    """Execute the generated SQL query and return results."""
    conn = connect_db()
    if not conn:
        return None

    cursor = conn.cursor()
    
    try:
        cursor.execute(sql_query)
        result = cursor.fetchall()
    except psycopg2.Error as e:
        print(f"Error executing SQL query: {e}")
        result = None

    cursor.close()
    conn.close()
    return result

# # Example Usage
# user_question = "Find activities where the athlete performed close to his best 'Ride' activity"
# sql_query = generate_sql_query(user_question)

# if sql_query:
#     try:
#         results = execute_sql_query(sql_query)
#         if results:
#             print("\nQuery Results:\n", results)
#     except Exception as e:
#         print(f"SQL query execution failed: {e}")
# else:
#     print("SQL query generation failed. Please check the error messages above.")