import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

# Add backend directory to sys.path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import cache_manager

class TestCacheManager(unittest.TestCase):

    def setUp(self):
        cache_manager.invalidate_all_caches()

    def test_extract_target_year(self):
        """Test year extraction from query strings."""
        self.assertEqual(cache_manager.extract_target_year("What was the longest run in 2024?"), 2024)
        self.assertEqual(cache_manager.extract_target_year("Best rides 2023"), 2023)
        self.assertIsNone(cache_manager.extract_target_year("What was my longest run ever?"))
        self.assertIsNone(cache_manager.extract_target_year("Longest run this month"))

    def test_is_historical_year(self):
        """Test historical year evaluation against current year."""
        current_year = datetime.now().year
        self.assertTrue(cache_manager.is_historical_year(current_year - 1))
        self.assertTrue(cache_manager.is_historical_year(current_year - 2))
        self.assertFalse(cache_manager.is_historical_year(current_year))
        self.assertFalse(cache_manager.is_historical_year(current_year + 1))
        self.assertFalse(cache_manager.is_historical_year(None))

    def test_embedding_cache(self):
        """Test in-memory embedding caching."""
        text = "Morning Run 5000m"
        dummy_vector = [0.1, 0.2, 0.3]
        
        self.assertIsNone(cache_manager.get_cached_embedding(text))
        cache_manager.set_cached_embedding(text, dummy_vector)
        self.assertEqual(cache_manager.get_cached_embedding(text), dummy_vector)

    def test_analytics_cache(self):
        """Test in-memory analytics caching."""
        dummy_data = {"summary": {"total": 10}, "activities": []}
        self.assertIsNone(cache_manager.get_cached_analytics("Run"))
        cache_manager.set_cached_analytics("Run", dummy_data)
        self.assertEqual(cache_manager.get_cached_analytics("Run"), dummy_data)

    def test_exact_query_memory_cache(self):
        """Test Tier 1 in-memory query caching."""
        query = "What was my longest run in 2024?"
        dummy_vector = [0.1] * 384
        response = "Your longest run was 15km on May 10, 2024."

        with patch('cache_manager.get_db_conn', return_value=None):
            cache_manager.set_semantic_cache(query, dummy_vector, response, query_type="rag")
            cached = cache_manager.get_semantic_cache(query, dummy_vector, query_type="rag")
            self.assertEqual(cached, response)

    def test_invalidation_clears_memory_cache(self):
        """Test that invalidation clears in-memory query & analytics caches."""
        query = "Longest run"
        dummy_vector = [0.1] * 384
        cache_manager.set_semantic_cache(query, dummy_vector, "10km", query_type="rag")
        cache_manager.set_cached_analytics("all", {"test": 1})

        with patch('cache_manager.get_db_conn', return_value=None):
            cache_manager.invalidate_cache_for_year(2024)
            self.assertIsNone(cache_manager.get_semantic_cache(query, dummy_vector, query_type="rag"))
            self.assertIsNone(cache_manager.get_cached_analytics("all"))

if __name__ == '__main__':
    unittest.main()
