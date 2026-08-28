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

class TestSqlRag(unittest.TestCase):

    def setUp(self):
        cache_manager.invalidate_all_caches()
        sql_rag.model.embed.return_value = iter([[0.1] * 384])

    def test_build_context_with_running_activity(self):
        """Test build_context formatting and pace calculation for runs."""
        sample_activities = [{
            'activity_id': '123456',
            'activity_type': 'Run',
            'distance': 10000.0,  # 10 km
            'duration': 3000,     # 50 mins = 5:00 min/km
            'timestamp': datetime(2026, 5, 10, 8, 0, 0),
            'similarity_score': 0.85
        }]

        context = sql_rag.build_context(sample_activities)
        self.assertIn("Run on 2026-05-10", context)
        self.assertIn("10.00km", context)
        self.assertIn("50m 0s", context)
        self.assertIn("Pace: 5:00/km", context)
        self.assertIn("ID: 123456", context)

    def test_build_context_empty(self):
        """Test build_context with empty list."""
        context = sql_rag.build_context([])
        self.assertEqual(context, "No activities found.")

    def test_build_context_workout_without_distance(self):
        """Test build_context for weight training without distance."""
        sample_activities = [{
            'activity_id': '789012',
            'activity_type': 'WeightTraining',
            'distance': None,
            'duration': 3600,  # 1 hour
            'timestamp': datetime(2026, 6, 1, 18, 0, 0),
            'similarity_score': 0.95
        }]

        context = sql_rag.build_context(sample_activities)
        self.assertIn("WeightTraining on 2026-06-01", context)
        self.assertIn("Distance: N/A", context)
        self.assertIn("1h 0m 0s", context)

    @patch('sql_rag.retrieve_similar_activities')
    @patch('sql_rag.generate_rag_response')
    def test_handle_rag_query_success(self, mock_generate, mock_retrieve):
        """Test handle_rag_query pipeline end-to-end with mocks."""
        mock_retrieve.return_value = [{
            'activity_id': '101',
            'activity_type': 'Run',
            'distance': 5000.0,
            'duration': 1500,
            'timestamp': datetime(2026, 7, 4, 9, 0, 0),
            'similarity_score': 0.92
        }]
        mock_generate.return_value = "You ran 5.0km on 2026-07-04 in 25 minutes."

        response = sql_rag.handle_rag_query("What was my run on July 4th?", debug=False)
        self.assertEqual(response, "You ran 5.0km on 2026-07-04 in 25 minutes.")
        mock_retrieve.assert_called_once()
        mock_generate.assert_called_once()

    @patch('sql_rag.retrieve_similar_activities')
    def test_handle_rag_query_no_results(self, mock_retrieve):
        """Test handle_rag_query when no activities are returned."""
        mock_retrieve.return_value = []
        response = sql_rag.handle_rag_query("Nonexistent query", debug=False)
        self.assertEqual(response, "I couldn't find any relevant activities to answer your question.")

if __name__ == '__main__':
    unittest.main()
