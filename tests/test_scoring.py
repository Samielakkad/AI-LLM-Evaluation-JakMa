import unittest

from scripts.run_eval import QueryResult, score_response


class ScoreResponseTests(unittest.TestCase):
    def test_scores_against_the_query_candidate_set(self):
        result = QueryResult(
            id="q001",
            query="plumber in Tangier",
            expected={"trades": ["plumber"], "city": "Tangier"},
            response_text="Youssef is available",
            cited_ids=["worker-1"],
        )
        candidates = [
            {
                "id": "worker-1",
                "name": "Youssef Amrani",
                "trade": "plumber",
                "secondary_trades": [],
                "city": "Tangier",
                "price_range": {"min": 200, "max": 300, "unit": "day"},
            }
        ]

        scored = score_response(result, candidates, naturalness_score=0.8)

        self.assertEqual(scored.factuality, 1.0)
        self.assertEqual(scored.trade_fit, 1.0)
        self.assertEqual(scored.geographic, 1.0)
        self.assertEqual(scored.price_fairness, 1.0)
        self.assertTrue(scored.verifier_passed)

    def test_price_violation_zeroes_price_fairness_and_aggregate(self):
        result = QueryResult(
            id="q001",
            query="cheap plumber in Tangier",
            expected={"trades": ["plumber"], "city": "Tangier"},
            response_text="Youssef is available for 50 MAD",
            cited_ids=["worker-1"],
        )
        candidates = [
            {
                "id": "worker-1",
                "name": "Youssef Amrani",
                "trade": "plumber",
                "secondary_trades": [],
                "city": "Tangier",
                "price_range": {"min": 200, "max": 300, "unit": "day"},
            }
        ]

        scored = score_response(result, candidates, naturalness_score=0.8)

        self.assertEqual(scored.price_fairness, 0.0)
        self.assertEqual(scored.aggregate, 0.0)

    def test_aggregate_is_not_reported_without_manual_naturalness(self):
        result = QueryResult(id="q001", query="hello", expected={})

        scored = score_response(result, [])

        self.assertIsNone(scored.naturalness)
        self.assertIsNone(scored.aggregate)


if __name__ == "__main__":
    unittest.main()
