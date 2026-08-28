import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock dependencies before importing backend modules
mock_modules = {
    'fastembed': MagicMock(),
    'psycopg2': MagicMock(),
    'psycopg2.pool': MagicMock(),
    'dotenv': MagicMock(),
    'requests': MagicMock(),
    'huggingface_hub': MagicMock()
}
sys.modules.update(mock_modules)

# Add backend directory to sys.path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import sql_generator

class TestSqlGuard(unittest.TestCase):

    def test_safe_select_queries_allowed(self):
        """Test that legitimate read-only SELECT queries pass validation."""
        valid_queries = [
            "SELECT activity_id, distance, duration FROM activities WHERE activity_type = 'Run' LIMIT 5;",
            "SELECT COUNT(*), AVG(distance) FROM activities WHERE EXTRACT(YEAR FROM timestamp) = 2026",
            "WITH recent AS (SELECT * FROM activities ORDER BY timestamp DESC LIMIT 10) SELECT * FROM recent",
            "SELECT activity_id, elevation_gain FROM activities ORDER BY elevation_gain DESC LIMIT 1;"
        ]
        for query in valid_queries:
            is_safe, reason = sql_generator.is_safe_sql(query)
            self.assertTrue(is_safe, f"Expected query to be safe: {query} (Reason: {reason})")

    def test_destructive_ddl_dml_blocked(self):
        """Test that destructive DDL/DML commands are rejected."""
        unsafe_queries = [
            "DROP TABLE activities;",
            "DELETE FROM activities WHERE distance < 1000",
            "UPDATE activities SET distance = 0",
            "INSERT INTO activities (activity_id) VALUES (12345)",
            "ALTER TABLE activities DROP COLUMN embedding",
            "TRUNCATE TABLE activities;",
            "GRANT ALL ON activities TO public;"
        ]
        for query in unsafe_queries:
            is_safe, reason = sql_generator.is_safe_sql(query)
            self.assertFalse(is_safe, f"Expected query to be blocked: {query}")
            self.assertTrue(len(reason) > 0)

    def test_statement_chaining_blocked(self):
        """Test that query stacking via semicolons is blocked."""
        stacked_query = "SELECT * FROM activities; DROP TABLE activities;"
        is_safe, reason = sql_generator.is_safe_sql(stacked_query)
        self.assertFalse(is_safe)
        self.assertIn("Multiple SQL statements", reason)

    def test_sensitive_table_access_blocked(self):
        """Test that attempts to query strava_tokens are blocked."""
        token_query = "SELECT * FROM strava_tokens;"
        is_safe, reason = sql_generator.is_safe_sql(token_query)
        self.assertFalse(is_safe)
        self.assertIn("strava_tokens", reason)

    def test_execute_sql_query_blocks_execution(self):
        """Test that execute_sql_query rejects unsafe query without connecting to DB."""
        with patch.object(sql_generator, 'connect_db') as mock_connect:
            result = sql_generator.execute_sql_query("DROP TABLE activities;")
            self.assertIsNone(result)
            mock_connect.assert_not_called()

if __name__ == '__main__':
    unittest.main()
