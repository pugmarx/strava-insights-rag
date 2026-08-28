import os
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Global connection pool
_pool = None

def get_pool():
    global _pool
    if _pool is None or _pool.closed:
        db_url = os.getenv("DATABASE_URL")
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = int(os.getenv("POSTGRES_PORT", 5432))
        dbname = os.getenv("POSTGRES_DB", "stravadb")
        user = os.getenv("POSTGRES_USER", "strava_user")
        password = os.getenv("POSTGRES_PASSWORD", "")
        sslmode = os.getenv("POSTGRES_SSLMODE", "prefer")

        try:
            if db_url:
                clean_url = db_url.strip().strip("\"'")
                _pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=10,
                    dsn=clean_url
                )
                print(">> DB Connection Pool initialized via DATABASE_URL")
            else:
                _pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=10,
                    host=host,
                    port=port,
                    dbname=dbname,
                    user=user,
                    password=password,
                    sslmode=sslmode
                )
                print(f">> DB Connection Pool initialized ({host}:{port}/{dbname}, sslmode={sslmode})")
        except psycopg2.Error as e:
            print(f"ERROR initializing DB pool: {e}")
            _pool = None
    return _pool

@contextmanager
def get_db_connection():
    """Context manager to borrow a connection from the pool and return it safely."""
    pool = get_pool()
    if pool is None:
        # Fallback to direct connection if pool failed to initialize
        conn = None
        try:
            db_url = os.getenv("DATABASE_URL")
            if db_url:
                conn = psycopg2.connect(db_url.strip().strip("\"'"))
            else:
                conn = psycopg2.connect(
                    host=os.getenv("POSTGRES_HOST", "localhost"),
                    port=int(os.getenv("POSTGRES_PORT", 5432)),
                    dbname=os.getenv("POSTGRES_DB", "stravadb"),
                    user=os.getenv("POSTGRES_USER", "strava_user"),
                    password=os.getenv("POSTGRES_PASSWORD", ""),
                    sslmode=os.getenv("POSTGRES_SSLMODE", "prefer")
                )
            yield conn
        finally:
            if conn:
                conn.close()
    else:
        conn = pool.getconn()
        try:
            yield conn
        finally:
            pool.putconn(conn)
