import requests
import os
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
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

# Initialize LLM Client
llm_client = LLMClient()

# Database connection
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

# LLM Query Function
def query_ollama(prompt):
    """Send a query to the LLM (Hugging Face / Groq / Ollama) and return the response."""
    return llm_client.generate(prompt)

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
    
    Use PostgreSQL syntax.
    
    ## Query Rules:
    - The `embedding` column stores a 384-dimensional vector representing the activity. It is used to find similar activities.
    - Use the `<=>` operator for cosine similarity between embeddings. It returns a FLOAT, not a BOOLEAN.
    - If using similarity in JOIN ON, always include a distance threshold (e.g., < 0.5), never mix with AND for other conditions.
    - Never use `<=>` directly in a JOIN ... ON clause unless it is wrapped in a comparison (e.g., `< 0.5`) or placed inside `ORDER BY`.
    - To find the most similar activity, use `<=>` inside an `ORDER BY` clause and `LIMIT 1`.
    - Use `timestamp` for time-based queries.
    - Use `distance` and `duration` for activity performance queries.
    - Use `embedding <=> embedding` for cosine similarity queries.
    - Use cosine similarity (`<=>`) on the `embedding` vector column when needed.
    - Always return `activity_id`, `activity_type`, `distance`, `duration`, and `timestamp` in the SELECT statement.
    - PostgreSQL does **not support** YEAR(timestamp). Instead, use: EXTRACT(YEAR FROM "timestamp")
    - Same for month: use EXTRACT(MONTH FROM "timestamp")
    - Use double quotes for column names when needed (like "timestamp")
    - Write SQL that finds similar runs using embedding comparison, and if you use subqueries or CTEs, make sure to include all columns that are referenced later (e.g. timestamp).
    - Just return the SQL query, no other meta information about the query.
    
    
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

    ### Example: Find the year with the least number of activities
    SELECT EXTRACT(YEAR FROM timestamp) AS activity_year, COUNT(*) AS total_activities
    FROM activities
    GROUP BY activity_year
    ORDER BY total_activities ASC
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


ACTIVITY_EMOJIS = {
    "Run": "🏃",
    "Ride": "🚴",
    "Swim": "🏊",
    "Walk": "🚶",
    "Hike": "🥾",
    "Workout": "💪",
    "Yoga": "🧘",
}

def format_results(results, cursor_description):
    """Format SQL query results using cursor description."""
    formatted = []
    column_names = [desc[0] for desc in cursor_description]

    for row in results:
        row_dict = dict(zip(column_names, row))
        formatted_row = {}

        for col, value in row_dict.items():
            if col == "activity_type":
                emoji = ACTIVITY_EMOJIS.get(value, "❓")
                #formatted_row["Activity"] = f"{emoji} {value}"
                formatted_row["Activity"] = f"{emoji}"
            elif col == "distance":
                formatted_row["Distance"] = f"{value / 1000:.1f} km"
            elif col == "duration":
                hours = value // 3600
                minutes = (value % 3600) // 60
                formatted_row["Duration"] = f"{hours}h {minutes}m"
            elif col == "timestamp":
                if isinstance(value, str):
                    value = datetime.fromisoformat(value)
                formatted_row["Date"] = value.strftime("%Y-%m-%d %H:%M")
            elif col == "activity_id":
                activity_url = f"https://www.strava.com/activities/{value}"
                formatted_row["Link"] = f'<a href="{activity_url}" target="_blank">View</a>'
                #formatted_row["link_html"] = f'<a href="{activity_url}" target="_blank">View</a>'
                #formatted_row["link"] = f"https://www.strava.com/activities/{value}"
            else:
                formatted_row[col] = value

        formatted.append(formatted_row)

    return formatted


def execute_sql_query(sql_query):
    """Execute the generated SQL query and return formatted results."""
    conn = connect_db()
    if not conn:
        return None

    cursor = conn.cursor()

    try:
        cursor.execute(sql_query)
        results = cursor.fetchall()
        formatted_results = format_results(results, cursor.description)
    except psycopg2.Error as e:
        print(f"Error executing SQL query: {e}")
        formatted_results = None

    cursor.close()
    conn.close()
    return formatted_results