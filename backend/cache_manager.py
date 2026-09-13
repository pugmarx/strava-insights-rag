import json
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


# ---------------------------------------------------------------------------
# Entity Extraction & Temporal Classification
# ---------------------------------------------------------------------------

def extract_query_entities(query_text: str) -> dict:
    """
    Extract discrete query entities to prevent semantic vector collisions:
    - sport_type: 'Ride', 'Run', 'Hike', 'Swim', 'Workout', or None
    - target_year: int (e.g. 2022, 2023, 2024) or None
    - target_month: int (1-12) or None
    - metric_intent: 'aggregation', 'elevation', 'speed', 'distance', 'duration', 'count', 'general'
    - superlative_dir: 'max', 'min', or None
    - item_limit: int or None
    - time_scope: 'historical_year', 'current_year', 'relative', 'relative_month', 'all_time'
    - is_historical: bool
    """
    if not query_text:
        return {
            "sport_type": None,
            "target_year": None,
            "target_month": None,
            "metric_intent": "general",
            "superlative_dir": None,
            "item_limit": None,
            "time_scope": "all_time",
            "is_historical": False
        }

    query_lower = query_text.lower()
    now = datetime.now()

    # 1. Sport Type Detection
    sport_type = None
    if any(w in query_lower for w in ["ride", "rides", "bike", "cycling", "cycl"]):
        sport_type = "Ride"
    elif any(w in query_lower for w in ["run", "runs", "running"]):
        sport_type = "Run"
    elif any(w in query_lower for w in ["hike", "hiking", "walk", "walking", "trek"]):
        sport_type = "Hike"
    elif any(w in query_lower for w in ["swim", "swimming"]):
        sport_type = "Swim"
    elif any(w in query_lower for w in ["workout", "workouts", "weight", "strength", "gym", "training"]):
        sport_type = "Workout"

    # 2. Target Year & Temporal Scope
    target_year = None
    year_match = re.search(r'\b(20\d{2})\b', query_text)
    if year_match:
        target_year = int(year_match.group(1))
    elif "this year" in query_lower:
        target_year = now.year
    elif "last year" in query_lower:
        target_year = now.year - 1

    is_historical = bool(target_year and target_year < now.year)

    # 3. Target Month Detection
    month_names = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12
    }
    target_month = None
    if "this month" in query_lower:
        target_month = now.month
    elif "last month" in query_lower:
        target_month = 12 if now.month == 1 else now.month - 1
    else:
        for m_name, m_num in month_names.items():
            if re.search(r'\b' + m_name + r'\b', query_lower):
                target_month = m_num
                break

    # Time scope classification
    if is_historical:
        time_scope = "historical_year"
    elif target_year == now.year:
        time_scope = "current_year"
    elif any(k in query_lower for k in ["last ", "past ", "recent", "this week", "this month", "last month", "latest"]):
        time_scope = "relative"
    elif target_month is not None:
        time_scope = "relative_month"
    else:
        time_scope = "all_time"

    # 4. Item Limit / Quantities
    word_to_num = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20
    }
    item_limit = None
    count_match = re.search(
        r'\b(?:last|latest|recent|past|previous|newest|top)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)\b',
        query_lower
    )
    if count_match:
        raw = count_match.group(1)
        item_limit = word_to_num.get(raw, int(raw) if raw.isdigit() else None)
    elif re.search(r'\b(?:last|latest|recent|past|previous|newest)\s+(?:ride|run|hike|walk|swim|workout|activity|session)\b', query_lower):
        item_limit = 1

    # 5. Superlative Direction (Max vs Min)
    superlative_dir = None
    if any(w in query_lower for w in ["longest", "fastest", "most", "highest", "max", "best", "hilliest", "top", "max elevation"]):
        superlative_dir = "max"
    elif any(w in query_lower for w in ["shortest", "slowest", "least", "lowest", "min", "flattest", "worst"]):
        superlative_dir = "min"

    # 6. Metric Intent
    if any(k in query_lower for k in ["how much", "how far", "how many", "how long", "total", "sum", "average", "avg", "overall distance", "annual summary", "volume", "stats"]):
        metric_intent = "aggregation"
    elif any(w in query_lower for w in ["climb", "climbs", "climbing", "elevation", "ascent", "mountain", "hill", "hilly"]):
        metric_intent = "elevation"
    elif any(w in query_lower for w in ["fastest", "speed", "pace", "slowest", "quickest"]):
        metric_intent = "speed"
    elif any(w in query_lower for w in ["longest", "distance", "shortest", "mileage", "km"]):
        metric_intent = "distance"
    elif any(w in query_lower for w in ["duration", "hours", "time spent", "minutes"]):
        metric_intent = "duration"
    elif any(w in query_lower for w in ["count", "frequency", "times did i"]):
        metric_intent = "count"
    else:
        metric_intent = "general"

    return {
        "sport_type": sport_type,
        "target_year": target_year,
        "target_month": target_month,
        "metric_intent": metric_intent,
        "superlative_dir": superlative_dir,
        "item_limit": item_limit,
        "time_scope": time_scope,
        "is_historical": is_historical
    }


def extract_target_year(query_text):
    """Extract explicit 4-digit calendar year from user query text if present (backwards compatibility)."""
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
    """Create query_cache table, columns, and vector index in PostgreSQL if not already existing."""
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
                    target_month INT,
                    sport_type VARCHAR(50),
                    metric_intent VARCHAR(50),
                    superlative_dir VARCHAR(20),
                    item_limit INT,
                    is_historical BOOLEAN DEFAULT FALSE,
                    embedding vector(384) NOT NULL,
                    response TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS target_month INT;
                ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS sport_type VARCHAR(50);
                ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS metric_intent VARCHAR(50);
                ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS superlative_dir VARCHAR(20);
                ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS item_limit INT;

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
# Tier 2: PostgreSQL Entity-Aware Semantic Vector Cache
# ---------------------------------------------------------------------------

def get_semantic_cache(query_text, query_vector, query_type="rag", similarity_threshold=None, entities=None):
    """
    Check Tier 1 (in-memory exact match with entity signature) followed by Tier 2 (PostgreSQL entity-aware semantic vector match).
    Enforces strict metadata equality on target_year, sport_type, item_limit, and superlative_dir to prevent entity drift.
    Returns cached response string/dict if found, otherwise None.
    """
    if entities is None:
        entities = extract_query_entities(query_text)

    entity_sig = tuple(sorted((k, str(v)) for k, v in entities.items() if k != "is_historical"))
    norm_key = (query_type, entity_sig, query_text.strip().lower())
    
    # 1. Tier 1: Check in-memory exact match
    mem_hit = _query_memory_cache.get(norm_key)
    if mem_hit:
        return mem_hit

    # 2. Tier 2: Check PostgreSQL semantic cache using vector cosine similarity & hard entity filters
    conn = get_db_conn()
    if not conn:
        return None

    target_year = entities.get("target_year")
    target_month = entities.get("target_month")
    sport_type = entities.get("sport_type")
    metric_intent = entities.get("metric_intent")
    superlative_dir = entities.get("superlative_dir")
    item_limit = entities.get("item_limit")

    # Dynamic threshold: strict (0.94) for entity-specific queries, standard (0.90) for open-ended descriptive queries
    has_discrete_entities = bool(target_year or target_month or item_limit or superlative_dir or (sport_type and sport_type != "Workout"))
    if similarity_threshold is None:
        threshold = 0.94 if has_discrete_entities else 0.90
    else:
        threshold = similarity_threshold

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT response, 1 - (embedding <=> %s::vector) AS similarity, query_text
                FROM query_cache
                WHERE query_type = %s
                  AND (target_year IS NOT DISTINCT FROM %s)
                  AND (target_month IS NOT DISTINCT FROM %s)
                  AND (sport_type IS NOT DISTINCT FROM %s)
                  AND (metric_intent IS NOT DISTINCT FROM %s)
                  AND (superlative_dir IS NOT DISTINCT FROM %s)
                  AND (item_limit IS NOT DISTINCT FROM %s)
                  AND (
                    is_historical = TRUE
                    OR (is_historical = FALSE AND created_at >= NOW() - INTERVAL '24 hours')
                  )
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY similarity DESC
                LIMIT 1;
            """, (
                query_vector,
                query_type,
                target_year,
                target_month,
                sport_type,
                metric_intent,
                superlative_dir,
                item_limit,
                query_vector,
                threshold
            ))
            row = cur.fetchone()
            if row and len(row) >= 3:
                raw_response, similarity, matched_query = row[0], row[1], row[2]
                print(f"[CacheManager] Semantic Cache HIT (similarity: {similarity:.3f}) for '{query_text}' -> matched '{matched_query}'")
                
                cached_val = raw_response
                if isinstance(raw_response, str) and raw_response.startswith("{") and '"response"' in raw_response:
                    try:
                        cached_val = json.loads(raw_response)
                    except Exception:
                        cached_val = raw_response

                # Populate Tier 1 in-memory cache for subsequent identical queries
                _query_memory_cache[norm_key] = cached_val
                return cached_val
    except Exception as e:
        print(f"[CacheManager] Error checking semantic cache: {e}")
    finally:
        conn.close()

    return None


def set_semantic_cache(query_text, query_vector, response, query_type="rag", entities=None):
    """Store generated response into Tier 1 (RAM) and Tier 2 (PostgreSQL) with discrete entity metadata."""
    if entities is None:
        entities = extract_query_entities(query_text)

    entity_sig = tuple(sorted((k, str(v)) for k, v in entities.items() if k != "is_historical"))
    norm_key = (query_type, entity_sig, query_text.strip().lower())
    _query_memory_cache[norm_key] = response

    target_year = entities.get("target_year")
    target_month = entities.get("target_month")
    sport_type = entities.get("sport_type")
    metric_intent = entities.get("metric_intent")
    superlative_dir = entities.get("superlative_dir")
    item_limit = entities.get("item_limit")
    historical = entities.get("is_historical", False)

    conn = get_db_conn()
    if not conn:
        return

    db_response = json.dumps(response) if isinstance(response, dict) else str(response)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO query_cache (
                    query_text, query_type, target_year, target_month, sport_type,
                    metric_intent, superlative_dir, item_limit, is_historical,
                    embedding, response
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                query_text,
                query_type,
                target_year,
                target_month,
                sport_type,
                metric_intent,
                superlative_dir,
                item_limit,
                historical,
                query_vector,
                db_response
            ))
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
