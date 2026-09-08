import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

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

import sql_rag
import cache_manager


class TestRecencyQueries(unittest.TestCase):

    def setUp(self):
        cache_manager.invalidate_all_caches()
        sql_rag.model.embed.return_value = iter([[0.1] * 384])

    def test_extract_recency_numbered_rides(self):
        """Test extraction for 'last 5 rides'."""
        is_rec, limit, is_gen = sql_rag.extract_recency_and_limit("What were my last 5 rides?")
        self.assertTrue(is_rec)
        self.assertEqual(limit, 5)
        self.assertFalse(is_gen)

    def test_extract_recency_numbered_activities(self):
        """Test extraction for 'last 10 activities'."""
        is_rec, limit, is_gen = sql_rag.extract_recency_and_limit("Show my last 10 activities")
        self.assertTrue(is_rec)
        self.assertEqual(limit, 10)
        self.assertTrue(is_gen)

    def test_extract_recency_word_numbers(self):
        """Test extraction for 'past three runs'."""
        is_rec, limit, is_gen = sql_rag.extract_recency_and_limit("tell me about my past three runs")
        self.assertTrue(is_rec)
        self.assertEqual(limit, 3)
        self.assertFalse(is_gen)

    def test_extract_recency_singular_ride(self):
        """Test extraction for 'last ride'."""
        is_rec, limit, is_gen = sql_rag.extract_recency_and_limit("Tell me about my last ride")
        self.assertTrue(is_rec)
        self.assertEqual(limit, 1)
        self.assertFalse(is_gen)

    def test_extract_recency_singular_activity(self):
        """Test extraction for 'latest activity'."""
        is_rec, limit, is_gen = sql_rag.extract_recency_and_limit("What was my latest activity?")
        self.assertTrue(is_rec)
        self.assertEqual(limit, 1)
        self.assertTrue(is_gen)

    def test_extract_recency_plural_without_number(self):
        """Test extraction for 'recent workouts'."""
        is_rec, limit, is_gen = sql_rag.extract_recency_and_limit("Show my recent activities")
        self.assertTrue(is_rec)
        self.assertEqual(limit, 5)
        self.assertTrue(is_gen)

    def test_non_recency_queries(self):
        """Test queries that are not recency queries."""
        is_rec, limit, is_gen = sql_rag.extract_recency_and_limit("What was my longest run in 2024?")
        self.assertFalse(is_rec)

    @patch('sql_rag.connect_db')
    def test_retrieve_similar_activities_recency_sql(self, mock_connect):
        """Verify that recency query executes with ORDER BY timestamp DESC and LIMIT."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        mock_cursor.fetchall.return_value = [
            (101, 'Ride', 25000.0, 3600, datetime(2026, 8, 1, 10, 0, 0), 150.0, 1.0),
            (102, 'Ride', 30000.0, 4200, datetime(2026, 7, 28, 9, 0, 0), 200.0, 1.0),
        ]

        activities = sql_rag.retrieve_similar_activities("last 2 rides")
        
        self.assertEqual(len(activities), 2)
        self.assertEqual(activities[0]['activity_id'], 101)
        self.assertEqual(activities[1]['activity_id'], 102)
        
        # Verify SQL query executed includes timestamp DESC and LIMIT 2
        call_args = mock_cursor.execute.call_args
        executed_sql = call_args[0][0]
        params = call_args[0][1]
        
        self.assertIn("ORDER BY timestamp DESC", executed_sql)
        self.assertIn("activity_type IN", executed_sql)
        self.assertEqual(params[-1], 2)


if __name__ == '__main__':
    unittest.main()
