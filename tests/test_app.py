import os
import sys
import unittest
import json
from unittest.mock import patch, MagicMock

# Mock third-party backend dependencies
mock_modules = {
    'fastembed': MagicMock(),
    'psycopg2': MagicMock(),
    'dotenv': MagicMock(),
    'huggingface_hub': MagicMock()
}
sys.modules.update(mock_modules)

# Add backend directory to sys.path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    import flask
    import flask_cors
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

@unittest.skipUnless(HAS_FLASK, "Flask is not installed in local environment")
class TestAppEndpoints(unittest.TestCase):

    def setUp(self):
        import app
        self.app = app.app.test_client()
        self.app.testing = True

    def test_health_endpoint(self):
        """Test /health endpoint returns healthy status."""
        response = self.app.get('/health')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("approach"), "RAG")

    def test_query_endpoint_empty_payload(self):
        """Test /query returns 400 when question is empty."""
        response = self.app.post('/query', 
                                 data=json.dumps({"question": ""}),
                                 content_type='application/json')
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn("error", data)

    def test_query_endpoint_too_long(self):
        """Test /query returns 400 when question exceeds 500 characters."""
        long_question = "run " * 150
        response = self.app.post('/query',
                                 data=json.dumps({"question": long_question}),
                                 content_type='application/json')
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn("error", data)
        self.assertIn("too long", data["error"])

    @patch('app.handle_rag_query')
    def test_query_endpoint_success(self, mock_handle_rag):
        """Test /query endpoint returns 200 with answer."""
        mock_handle_rag.return_value = "Your longest run was 15km."
        response = self.app.post('/query',
                                 data=json.dumps({"question": "What was my longest run?"}),
                                 content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get("response"), "Your longest run was 15km.")
        self.assertEqual(data.get("approach"), "RAG")

    @patch('app.hybrid_query_handler')
    def test_hybrid_query_endpoint_success(self, mock_hybrid):
        """Test /hybrid-query endpoint returns 200."""
        mock_hybrid.return_value = "Total distance is 120km."
        response = self.app.post('/hybrid-query',
                                 data=json.dumps({"question": "What is my total distance in 2026?"}),
                                 content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get("response"), "Total distance is 120km.")
        self.assertEqual(data.get("approach"), "Hybrid RAG+SQL")

if __name__ == '__main__':
    unittest.main()
