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

backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import sql_rag
import strava_service


class TestRoutes(unittest.TestCase):

    def test_extract_map_data_from_activities(self):
        """Test extraction of routes for map rendering."""
        activities = [
            {
                'activity_id': 101,
                'activity_type': 'Ride',
                'distance': 25000.0,
                'duration': 3600,
                'elevation_gain': 150.0,
                'summary_polyline': '_zfpBafabMR|BLr...',
                'timestamp': datetime(2026, 8, 20, 10, 0, 0)
            },
            {
                'activity_id': 102,
                'activity_type': 'WeightTraining',
                'distance': 0.0,
                'duration': 1800,
                'elevation_gain': 0.0,
                'summary_polyline': None,
                'timestamp': datetime(2026, 8, 21, 10, 0, 0)
            },
            {
                'activity_id': 103,
                'activity_type': 'Run',
                'distance': 5000.0,
                'duration': 1500,
                'elevation_gain': 30.0,
                'summary_polyline': 'abcdEfghIjkl...',
                'timestamp': datetime(2026, 8, 22, 10, 0, 0)
            }
        ]

        map_data = sql_rag.extract_map_data_from_activities(activities)
        self.assertIsNotNone(map_data)
        self.assertEqual(map_data['route_count'], 2)
        self.assertEqual(len(map_data['routes']), 2)

        ride_route = map_data['routes'][0]
        self.assertEqual(ride_route['activity_id'], 101)
        self.assertEqual(ride_route['activity_type'], 'Ride')
        self.assertEqual(ride_route['distance_km'], 25.0)
        self.assertEqual(ride_route['speed_kmh'], 25.0)
        self.assertEqual(ride_route['summary_polyline'], '_zfpBafabMR|BLr...')

        run_route = map_data['routes'][1]
        self.assertEqual(run_route['activity_id'], 103)
        self.assertEqual(run_route['activity_type'], 'Run')
        self.assertEqual(run_route['distance_km'], 5.0)
        self.assertEqual(run_route['pace'], '5:00/km')

    def test_extract_map_data_none_when_no_polylines(self):
        """Test that map_data is None if activities have no polylines."""
        activities = [
            {
                'activity_id': 201,
                'activity_type': 'WeightTraining',
                'distance': 0.0,
                'duration': 1800,
                'summary_polyline': None,
                'timestamp': datetime(2026, 8, 21, 10, 0, 0)
            }
        ]
        self.assertIsNone(sql_rag.extract_map_data_from_activities(activities))
        self.assertIsNone(sql_rag.extract_map_data_from_activities([]))

    @patch('strava_service.get_db_connection')
    @patch('strava_service.get_valid_access_token')
    @patch('strava_service.requests.get')
    def test_get_activity_streams_caching(self, mock_requests_get, mock_token, mock_db_conn):
        """Test that get_activity_streams correctly processes streams and calculates milestone points."""
        # Mock DB returning empty (no cache hit)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db_conn.return_value = mock_conn

        mock_token.return_value = "mock_token_123"

        # Mock Strava streams API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "latlng": {"data": [[18.5, 73.8], [18.51, 73.81], [18.52, 73.82]]},
            "velocity_smooth": {"data": [3.0, 10.0, 5.0]},  # 10.0 m/s = 36 km/h max speed
            "altitude": {"data": [550.0, 620.0, 580.0]},     # 620m max altitude
            "time": {"data": [0, 60, 120]},
            "distance": {"data": [0, 500, 1000]}
        }
        mock_requests_get.return_value = mock_response

        streams_result = strava_service.get_activity_streams(999)
        self.assertTrue(streams_result['has_streams'])
        self.assertEqual(streams_result['point_count'], 3)
        self.assertEqual(streams_result['max_speed_kmh'], 36.0)
        self.assertEqual(streams_result['peak_altitude_m'], 620.0)
        self.assertEqual(streams_result['top_speed_point']['speed_kmh'], 36.0)
        self.assertEqual(streams_result['peak_altitude_point']['altitude_m'], 620.0)
        self.assertEqual(streams_result['start_point']['lat'], 18.5)
        self.assertEqual(streams_result['finish_point']['lat'], 18.52)


if __name__ == '__main__':
    unittest.main()
