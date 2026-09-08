import os
import sys
import unittest
import json
import tempfile
import shutil
from unittest.mock import MagicMock, patch

# Mock third-party dependencies before importing backend modules
mock_modules = {
    'fastembed': MagicMock(),
    'psycopg2': MagicMock(),
    'psycopg2.pool': MagicMock(),
    'dotenv': MagicMock(),
    'requests': MagicMock(),
    'huggingface_hub': MagicMock(),
    'numpy': MagicMock()
}
sys.modules.update(mock_modules)

# Add backend directory to sys.path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import query_logger


class TestQueryLogger(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_logs_dir = query_logger.LOGS_DIR
        self.original_audit_file = query_logger.AUDIT_LOG_FILE
        self.original_log_failed_only = query_logger.LOG_FAILED_ONLY
        query_logger.LOGS_DIR = self.temp_dir
        query_logger.AUDIT_LOG_FILE = os.path.join(self.temp_dir, "query_audit.jsonl")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        query_logger.LOGS_DIR = self.original_logs_dir
        query_logger.AUDIT_LOG_FILE = self.original_audit_file
        query_logger.LOG_FAILED_ONLY = self.original_log_failed_only

    @patch('query_logger.get_db_connection')
    def test_log_query_event_all_mode(self, mock_get_conn):
        """Test logging successful query event when LOG_FAILED_ONLY is False."""
        query_logger.LOG_FAILED_ONLY = False
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        query_logger.log_query_event(
            query_text="What was my last ride?",
            approach="rag",
            status="SUCCESS",
            retrieved_count=1,
            response="Your last ride was 30km.",
            latency_ms=120,
            async_log=False
        )

        # Check local file
        self.assertTrue(os.path.exists(query_logger.AUDIT_LOG_FILE))
        with open(query_logger.AUDIT_LOG_FILE, "r") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 1)
            data = json.loads(lines[0])
            self.assertEqual(data["query_text"], "What was my last ride?")
            self.assertEqual(data["status"], "SUCCESS")
            self.assertEqual(data["retrieved_count"], 1)

    @patch('query_logger.get_db_connection')
    def test_log_query_event_failed_only_mode(self, mock_get_conn):
        """Test that LOG_FAILED_ONLY=True skips successful queries but logs failures and zero-result queries."""
        query_logger.LOG_FAILED_ONLY = True
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        # 1. Clean success with retrieved_count > 0 -> Should NOT be logged
        query_logger.log_query_event(
            query_text="Show my runs",
            approach="rag",
            status="SUCCESS",
            retrieved_count=5,
            response="Found 5 runs",
            async_log=False
        )
        self.assertFalse(os.path.exists(query_logger.AUDIT_LOG_FILE))

        # 2. Query with 0 retrieved items -> Should be logged
        query_logger.log_query_event(
            query_text="Show my swimming activities",
            approach="rag",
            status="SUCCESS",
            retrieved_count=0,
            response="No activities found",
            async_log=False
        )
        self.assertTrue(os.path.exists(query_logger.AUDIT_LOG_FILE))

        # 3. Query with ERROR status -> Should be logged
        query_logger.log_query_event(
            query_text="Error query",
            approach="rag",
            status="ERROR",
            error_message="Database timeout",
            async_log=False
        )

        # 4. Query with NO_RESULTS status -> Should be logged
        query_logger.log_query_event(
            query_text="No results query",
            approach="rag",
            status="NO_RESULTS",
            async_log=False
        )

        with open(query_logger.AUDIT_LOG_FILE, "r") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 3)
            data = [json.loads(line) for line in lines]
            queries = [d["query_text"] for d in data]
            self.assertNotIn("Show my runs", queries)
            self.assertIn("Show my swimming activities", queries)
            self.assertIn("Error query", queries)
            self.assertIn("No results query", queries)

    @patch('query_logger.get_db_connection')
    def test_fetch_failed_queries_fallback(self, mock_get_conn):
        """Test retrieving failed queries from JSONL audit log when DB is None."""
        query_logger.LOG_FAILED_ONLY = False
        mock_get_conn.return_value = None  # DB unavailable

        # Log 1 success and 2 failures
        query_logger.log_query_event(
            query_text="valid query",
            status="SUCCESS",
            retrieved_count=1,
            async_log=False
        )
        query_logger.log_query_event(
            query_text="unanswerable question 1",
            status="NO_RESULTS",
            error_message="No matching activities",
            async_log=False
        )
        query_logger.log_query_event(
            query_text="error query 2",
            status="ERROR",
            error_message="Timeout connecting to LLM",
            async_log=False
        )

        failed = query_logger.fetch_failed_queries(limit=10, days=7)
        self.assertEqual(len(failed), 2)
        failed_texts = [f["query_text"] for f in failed]
        self.assertIn("unanswerable question 1", failed_texts)
        self.assertIn("error query 2", failed_texts)

    @patch('query_logger.get_db_connection')
    def test_get_query_health_summary(self, mock_get_conn):
        """Test computing health summary metrics."""
        query_logger.LOG_FAILED_ONLY = False
        mock_get_conn.return_value = None  # DB fallback

        query_logger.log_query_event("q1", status="SUCCESS", retrieved_count=1, latency_ms=100, async_log=False)
        query_logger.log_query_event("q2", status="SUCCESS", retrieved_count=1, latency_ms=200, async_log=False)
        query_logger.log_query_event("q3", status="NO_RESULTS", retrieved_count=0, latency_ms=50, async_log=False)

        summary = query_logger.get_query_health_summary(days=7)
        self.assertEqual(summary["total_queries"], 3)
        self.assertEqual(summary["successful_queries"], 2)
        self.assertEqual(summary["no_results_queries"], 1)
        self.assertEqual(summary["success_rate_percent"], 66.7)


if __name__ == '__main__':
    unittest.main()

