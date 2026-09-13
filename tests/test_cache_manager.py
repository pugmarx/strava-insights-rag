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

    def test_extract_query_entities(self):
        """Test comprehensive entity extraction across sports, years, months, metrics, and limits."""
        e1 = cache_manager.extract_query_entities("how much did i ride in 2023")
        self.assertEqual(e1["sport_type"], "Ride")
        self.assertEqual(e1["target_year"], 2023)
        self.assertEqual(e1["metric_intent"], "aggregation")
        self.assertTrue(e1["is_historical"])

        e2 = cache_manager.extract_query_entities("how much did i ride in 2022")
        self.assertEqual(e2["sport_type"], "Ride")
        self.assertEqual(e2["target_year"], 2022)
        self.assertEqual(e2["metric_intent"], "aggregation")

        e3 = cache_manager.extract_query_entities("last 5 rides")
        self.assertEqual(e3["sport_type"], "Ride")
        self.assertEqual(e3["item_limit"], 5)
        self.assertEqual(e3["time_scope"], "relative")

        e4 = cache_manager.extract_query_entities("last 10 rides")
        self.assertEqual(e4["sport_type"], "Ride")
        self.assertEqual(e4["item_limit"], 10)

        e5 = cache_manager.extract_query_entities("fastest bike ride")
        self.assertEqual(e5["sport_type"], "Ride")
        self.assertEqual(e5["metric_intent"], "speed")
        self.assertEqual(e5["superlative_dir"], "max")

        e6 = cache_manager.extract_query_entities("slowest run")
        self.assertEqual(e6["sport_type"], "Run")
        self.assertEqual(e6["metric_intent"], "speed")
        self.assertEqual(e6["superlative_dir"], "min")

    def test_no_cross_year_cache_collision(self):
        """Ensure 2023 and 2022 queries do NOT collide in cache."""
        dummy_vector = [0.1] * 384
        q2023 = "how much did i ride in 2023"
        q2022 = "how much did i ride in 2022"

        with patch('cache_manager.get_db_conn', return_value=None):
            cache_manager.set_semantic_cache(q2023, dummy_vector, "2023 Stats: 3000km", query_type="rag")
            cached_2023 = cache_manager.get_semantic_cache(q2023, dummy_vector, query_type="rag")
            cached_2022 = cache_manager.get_semantic_cache(q2022, dummy_vector, query_type="rag")

            self.assertEqual(cached_2023, "2023 Stats: 3000km")
            self.assertIsNone(cached_2022, "2022 query must not collide with 2023 cache entry")

    def test_no_cross_limit_cache_collision(self):
        """Ensure 'last 5' and 'last 10' queries do NOT collide in cache."""
        dummy_vector = [0.1] * 384
        q5 = "last 5 rides"
        q10 = "last 10 rides"

        with patch('cache_manager.get_db_conn', return_value=None):
            cache_manager.set_semantic_cache(q5, dummy_vector, "5 rides list", query_type="rag")
            self.assertEqual(cache_manager.get_semantic_cache(q5, dummy_vector, query_type="rag"), "5 rides list")
            self.assertIsNone(cache_manager.get_semantic_cache(q10, dummy_vector, query_type="rag"))

    def test_no_cross_sport_cache_collision(self):
        """Ensure 'longest run' and 'longest ride' do NOT collide in cache."""
        dummy_vector = [0.1] * 384
        q_run = "longest run"
        q_ride = "longest ride"

        with patch('cache_manager.get_db_conn', return_value=None):
            cache_manager.set_semantic_cache(q_run, dummy_vector, "Longest Run: 21km", query_type="rag")
            self.assertEqual(cache_manager.get_semantic_cache(q_run, dummy_vector, query_type="rag"), "Longest Run: 21km")
            self.assertIsNone(cache_manager.get_semantic_cache(q_ride, dummy_vector, query_type="rag"))


if __name__ == '__main__':
    unittest.main()
