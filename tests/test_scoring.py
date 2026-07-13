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
            }
        ]

        scored = score_response(result, candidates)

        self.assertEqual(scored.factuality, 1.0)
        self.assertEqual(scored.trade_fit, 1.0)
        self.assertEqual(scored.geographic, 1.0)
        self.assertTrue(scored.verifier_passed)


if __name__ == "__main__":
    unittest.main()
