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

    def test_extract_chart_data_from_activities(self):
        """Test extraction of chronological chart datapoints."""
        activities = [
            {
                'activity_id': '102',
                'activity_type': 'Run',
                'distance': 10000.0,
                'elevation_gain': 120.0,
                'duration': 3000,
                'timestamp': datetime(2026, 8, 15, 8, 0, 0)
            },
            {
                'activity_id': '101',
                'activity_type': 'Run',
                'distance': 5000.0,
                'elevation_gain': 45.0,
                'duration': 1500,
                'timestamp': datetime(2026, 8, 1, 8, 0, 0)
            }
        ]
        chart_data = sql_rag.extract_chart_data_from_activities(activities)
        self.assertIsNotNone(chart_data)
        self.assertEqual(len(chart_data['labels']), 2)
        # Should be sorted chronologically
        self.assertEqual(chart_data['labels'][0], "2026-08-01")
        self.assertEqual(chart_data['labels'][1], "2026-08-15")
        self.assertEqual(chart_data['distances'], [5.0, 10.0])
        self.assertEqual(chart_data['elevations'], [45.0, 120.0])
        self.assertEqual(chart_data['points'][0]['pace'], "5:00/km")

    def test_build_context_with_exact_aggregates(self):
        """Test build_context formatting when exact database aggregates are provided."""
        exact = {
            "count": 42,
            "total_distance_km": 1850.5,
            "total_duration_sec": 216000,  # 60h 0m
            "total_elevation_m": 24500.0,
            "max_distance_km": 105.2,
            "avg_distance_km": 44.06,
            "avg_duration_sec": 5142
        }
        context = sql_rag.build_context([], exact_aggregates=exact)
        self.assertIn("EXACT DATABASE TOTALS", context)
        self.assertIn("Total Activities Logged: 42", context)
        self.assertIn("Total Distance: 1850.50 km", context)
        self.assertIn("Total Moving Time: 60h 0m", context)
        self.assertIn("Total Elevation Gain: 24500 m", context)
        self.assertIn("Longest Single Activity: 105.20 km", context)

    @patch('sql_rag.connect_db')
    def test_execute_exact_aggregation_sql(self, mock_connect):
        """Test SQL aggregation query execution and dictionary parsing."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # COUNT, SUM(distance), SUM(duration), SUM(elevation_gain), MAX(distance), AVG(distance), AVG(duration)
        mock_cursor.fetchone.return_value = (15, 600000.0, 72000, 8500.0, 65000.0, 40000.0, 4800)

        result = sql_rag.execute_exact_aggregation(matched_types=['Ride'], time_filters=["EXTRACT(YEAR FROM timestamp) = 2023"])
        self.assertIsNotNone(result)
        self.assertEqual(result["count"], 15)
        self.assertEqual(result["total_distance_km"], 600.0)
        self.assertEqual(result["total_duration_sec"], 72000)
        self.assertEqual(result["total_elevation_m"], 8500.0)
        self.assertEqual(result["max_distance_km"], 65.0)
        self.assertEqual(result["avg_distance_km"], 40.0)


if __name__ == '__main__':
    unittest.main()
