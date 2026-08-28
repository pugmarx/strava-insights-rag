import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

# Mock third-party dependencies before importing backend modules
mock_modules = {
    'fastembed': MagicMock(),
    'psycopg2': MagicMock(),
    'psycopg2.pool': MagicMock(),
    'dotenv': MagicMock(),
    'requests': MagicMock(),
    'huggingface_hub': MagicMock()
}
for mod_name, mod_mock in mock_modules.items():
    if mod_name not in sys.modules:
        sys.modules[mod_name] = mod_mock

# Add backend directory to sys.path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import strava_service
import token_manager

class TestStravaService(unittest.TestCase):

    def test_parse_strava_timestamp(self):
        """Test parsing ISO 8601 strings from Strava."""
        iso_str = "2026-08-25T14:30:00Z"
        dt = strava_service.parse_strava_timestamp(iso_str)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 8)
        self.assertEqual(dt.day, 25)
        self.assertEqual(dt.hour, 14)
        self.assertEqual(dt.minute, 30)

    def test_format_activity_text(self):
        """Test format of activity text for embedding."""
        activity = {
            "name": "Morning Tempo Run",
            "type": "Run",
            "distance": 8500.0,
            "elapsed_time": 2400
        }
        text = strava_service.format_activity_text(activity)
        self.assertEqual(text, "Morning Tempo Run Run 8500.0 meters in 2400 seconds")

    @patch('strava_service.get_db_connection')
    @patch('strava_service.compute_embedding')
    @patch('strava_service.fetch_activity_from_strava')
    def test_sync_single_activity(self, mock_fetch, mock_embed, mock_db_conn):
        """Test syncing a single activity end-to-end."""
        mock_fetch.return_value = {
            "id": 9991234,
            "name": "Intervals",
            "type": "Run",
            "distance": 5000.0,
            "elapsed_time": 1500,
            "start_date": "2026-08-25T07:00:00Z",
            "athlete": {"id": 12345}
        }
        mock_embed.return_value = [0.1] * 384

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn

        res = strava_service.sync_single_activity(9991234)
        self.assertEqual(res["id"], 9991234)
        mock_fetch.assert_called_once_with(9991234)
        mock_embed.assert_called_once()
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch('strava_service.get_db_connection')
    def test_delete_activity(self, mock_db_conn):
        """Test activity deletion."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn

        success = strava_service.delete_activity(9991234)
        self.assertTrue(success)
        mock_cursor.execute.assert_called_once_with(
            "DELETE FROM activities WHERE activity_id = %s", (9991234,)
        )
        mock_conn.commit.assert_called_once()

    @patch('strava_service.requests.get')
    @patch('strava_service.get_valid_access_token')
    @patch('strava_service.get_latest_activity_timestamp')
    @patch('strava_service.save_activity_to_db')
    def test_sync_incremental(self, mock_save, mock_latest_ts, mock_token, mock_http_get):
        """Test incremental sync fetching latest activities."""
        mock_token.return_value = "mock_access_token"
        mock_latest_ts.return_value = datetime(2026, 8, 20, 10, 0, 0)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1001, "name": "Ride 1", "type": "Ride", "distance": 20000, "elapsed_time": 3600, "start_date": "2026-08-21T10:00:00Z"},
            {"id": 1002, "name": "Run 1", "type": "Run", "distance": 6000, "elapsed_time": 1800, "start_date": "2026-08-22T10:00:00Z"}
        ]
        mock_http_get.return_value = mock_response

        result = strava_service.sync_incremental(limit=50)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["synced_count"], 2)
        self.assertEqual(mock_save.call_count, 2)


class TestTokenManager(unittest.TestCase):

    @patch('token_manager.get_tokens_from_db')
    def test_get_valid_access_token_unexpired(self, mock_db_tokens):
        """Test returning access token directly when still valid."""
        import time
        mock_db_tokens.return_value = {
            "access_token": "valid_token_123",
            "refresh_token": "refresh_token_456",
            "expires_at": time.time() + 3600  # Expires in 1 hour
        }

        token = token_manager.get_valid_access_token()
        self.assertEqual(token, "valid_token_123")

    @patch('token_manager.refresh_strava_token')
    @patch('token_manager.get_tokens_from_db')
    def test_get_valid_access_token_expired_triggers_refresh(self, mock_db_tokens, mock_refresh):
        """Test refreshing token when expired."""
        import time
        mock_db_tokens.return_value = {
            "access_token": "expired_token_123",
            "refresh_token": "refresh_token_456",
            "expires_at": time.time() - 100  # Expired
        }
        mock_refresh.return_value = {
            "access_token": "new_fresh_token_789",
            "refresh_token": "new_refresh_token_000",
            "expires_at": time.time() + 21600
        }

        token = token_manager.get_valid_access_token()
        self.assertEqual(token, "new_fresh_token_789")
        mock_refresh.assert_called_once_with("refresh_token_456")


if __name__ == '__main__':
    unittest.main()
