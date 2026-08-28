import re
import time
from datetime import datetime
import psycopg2

try:
    from cachetools import TTLCache
except ImportError:
    # Lightweight in-memory TTL cache fallback if cachetools is not installed yet
    class TTLCache(dict):
        def __init__(self, maxsize=256, ttl=1800):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl
            self._timestamps = {}

        def __getitem__(self, key):
            if key not in self:
                raise KeyError(key)
            if time.time() - self._timestamps.get(key, 0) > self.ttl:
                del self[key]
                raise KeyError(key)
            return super().__getitem__(key)

        def __setitem__(self, key, value):
            if len(self) >= self.maxsize and key not in self:
                # Remove oldest
                oldest_key = min(self._timestamps, key=self._timestamps.get, default=None)
                if oldest_key:
                    del self[oldest_key]
            self._timestamps[key] = time.time()
            super().__setitem__(key, value)

        def __delitem__(self, key):
            self._timestamps.pop(key, None)
            super().__delitem__(key)

        def get(self, key, default=None):
            try:
                return self[key]
            except KeyError:
                return default

        def clear(self):
            self._timestamps.clear()
            super().clear()

# ---------------------------------------------------------------------------
# Tier 1: In-Memory TTL Caches
# ---------------------------------------------------------------------------
# 1. Vector embedding cache (1 hour TTL)
_embedding_cache = TTLCache(maxsize=512, ttl=3600)

# 2. Query response cache for exact memory hits (30 minutes TTL)
_query_memory_cache = TTLCache(maxsize=256, ttl=1800)

# 3. Analytics response cache (30 minutes TTL)
_analytics_cache = TTLCache(maxsize=32, ttl=1800)


def get_cached_embedding(text):
    """Retrieve pre-computed embedding from in-memory cache."""
    return _embedding_cache.get(text.strip().lower())


def set_cached_embedding(text, embedding):
    """Store computed embedding in in-memory cache."""
    _embedding_cache[text.strip().lower()] = embedding


def extract_target_year(query_text):
    """Extract explicit 4-digit calendar year from user query text if present."""
    if not query_text:
        return None
    match = re.search(r'\b(20\d{2})\b', query_text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def is_historical_year(target_year):
    """
    Evaluate if target_year is historical.
    A year is historical if it is strictly before the current calendar year.
    """
    if not target_year:
        return False
    current_year = datetime.now().year
    return target_year < current_year


def get_db_conn():
    """Import DB connection from token_manager to avoid circular imports."""
    from token_manager import get_db_connection
    return get_db_connection()


def init_cache_table():
    """Create query_cache table and vector index in PostgreSQL if not already existing."""
    conn = get_db_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS query_cache (
                    id SERIAL PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    query_type VARCHAR(20) DEFAULT 'rag',
                    target_year INT,
                    is_historical BOOLEAN DEFAULT FALSE,
                    embedding vector(384) NOT NULL,
                    response TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS query_cache_embedding_idx 
                ON query_cache USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 20);
            """)
            conn.commit()
            print("[CacheManager] Verified query_cache table & index.")
    except Exception as e:
        print(f"[CacheManager] Table init notice: {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tier 2: PostgreSQL Semantic Vector Cache
# ---------------------------------------------------------------------------

def get_semantic_cache(query_text, query_vector, query_type="rag", similarity_threshold=0.92):
    """
    Check Tier 1 (in-memory exact match) followed by Tier 2 (PostgreSQL semantic vector match).
    Returns cached response string if found, otherwise None.
    """
    norm_key = (query_type, query_text.strip().lower())
    
    # 1. Tier 1: Check in-memory exact match
    mem_hit = _query_memory_cache.get(norm_key)
    if mem_hit:
        return mem_hit

    # 2. Tier 2: Check PostgreSQL semantic cache using vector cosine similarity
    conn = get_db_conn()
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT response, 1 - (embedding <=> %s::vector) AS similarity, query_text
                FROM query_cache
                WHERE query_type = %s
                  AND (
                    is_historical = TRUE
                    OR (is_historical = FALSE AND created_at >= NOW() - INTERVAL '24 hours')
                  )
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY similarity DESC
                LIMIT 1;
            """, (query_vector, query_type, query_vector, similarity_threshold))
            row = cur.fetchone()
            if row and len(row) >= 3:
                response, similarity, matched_query = row[0], row[1], row[2]
                print(f"[CacheManager] Semantic Cache HIT (similarity: {similarity:.3f}) for '{query_text}' -> matched '{matched_query}'")
                # Populate Tier 1 in-memory cache for subsequent identical queries
                _query_memory_cache[norm_key] = response
                return response
    except Exception as e:
        print(f"[CacheManager] Error checking semantic cache: {e}")
    finally:
        conn.close()

    return None


def set_semantic_cache(query_text, query_vector, response, query_type="rag"):
    """Store generated response into Tier 1 (RAM) and Tier 2 (PostgreSQL)."""
    norm_key = (query_type, query_text.strip().lower())
    _query_memory_cache[norm_key] = response

    target_year = extract_target_year(query_text)
    historical = is_historical_year(target_year)

    conn = get_db_conn()
    if not conn:
        return

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO query_cache (query_text, query_type, target_year, is_historical, embedding, response)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (query_text, query_type, target_year, historical, query_vector, response))
            conn.commit()
    except Exception as e:
        print(f"[CacheManager] Error storing to query_cache table: {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Invalidation & Refresh Logic
# ---------------------------------------------------------------------------

def invalidate_cache_for_year(activity_year):
    """
    Invalidate queries for a specific affected year and all floating/relative queries.
    Historical queries for other years remain untouched in the database.
    """
    # 1. Clear in-memory query & analytics caches
    _query_memory_cache.clear()
    _analytics_cache.clear()

    # 2. Invalidate affected year in PostgreSQL
    conn = get_db_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            if activity_year:
                cur.execute("""
                    DELETE FROM query_cache 
                    WHERE target_year = %s 
                       OR target_year IS NULL;
                """, (activity_year,))
            else:
                cur.execute("DELETE FROM query_cache WHERE target_year IS NULL;")
            conn.commit()
            print(f"[CacheManager] Invalidated cache entries for year {activity_year} and relative queries.")
    except Exception as e:
        print(f"[CacheManager] Error invalidating cache for year {activity_year}: {e}")
    finally:
        conn.close()


def invalidate_all_caches():
    """Completely wipe both in-memory and database query caches."""
    _query_memory_cache.clear()
    _analytics_cache.clear()
    _embedding_cache.clear()

    conn = get_db_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE query_cache;")
            conn.commit()
            print("[CacheManager] Wiped all in-memory and database query caches.")
    except Exception as e:
        print(f"[CacheManager] Error truncating query_cache: {e}")
    finally:
        conn.close()


def get_cached_analytics(filter_key):
    """Retrieve cached analytics dictionary if present."""
    return _analytics_cache.get(filter_key or "all")


def set_cached_analytics(filter_key, data):
    """Store analytics calculation in memory cache."""
    _analytics_cache[filter_key or "all"] = data
