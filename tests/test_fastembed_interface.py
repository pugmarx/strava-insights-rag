import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock dependencies before importing backend modules
mock_embedding_instance = MagicMock()
mock_TextEmbedding = MagicMock(return_value=mock_embedding_instance)

mock_modules = {
    'fastembed': MagicMock(TextEmbedding=mock_TextEmbedding),
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

import sql_rag

class TestFastEmbedIntegration(unittest.TestCase):

    def test_compute_embedding_with_list(self):
        """Test compute_embedding when embed() returns a list."""
        fake_vector = [0.123] * 384
        mock_embedding_instance.embed.return_value = iter([fake_vector])

        embedding = sql_rag.compute_embedding("test query")
        self.assertIsInstance(embedding, list)
        self.assertEqual(len(embedding), 384)
        self.assertEqual(embedding[0], 0.123)

    def test_compute_embedding_with_mock_array_like_tolist(self):
        """Test compute_embedding when embed() returns an object with .tolist() (e.g. numpy ndarray)."""
        class FakeNumpyArray:
            def __init__(self, data):
                self._data = data
            def tolist(self):
                return self._data

        mock_embedding_instance.embed.return_value = iter([FakeNumpyArray([0.456] * 384)])

        embedding = sql_rag.compute_embedding("test query")
        self.assertIsInstance(embedding, list)
        self.assertEqual(len(embedding), 384)
        self.assertEqual(embedding[0], 0.456)

    def test_retrieve_similar_activities_flow(self):
        """Test full retrieve_similar_activities flow with mocked DB."""
        fake_vector = [0.0] * 384
        mock_embedding_instance.embed.return_value = iter([fake_vector])

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ('act_1', 'Run', 5000.0, 1500, '2026-01-01', 0.95)
        ]

        with patch.object(sql_rag, 'connect_db', return_value=mock_conn):
            results = sql_rag.retrieve_similar_activities("morning run", top_k=5)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['activity_id'], 'act_1')
            self.assertEqual(results[0]['similarity_score'], 0.95)

if __name__ == '__main__':
    unittest.main()
