import unittest

from scripts.verifier import verify_grounding


CANDIDATES = [
    {
        "id": "worker-1",
        "name": "Youssef Amrani",
        "phone": "0612345678",
        "trade": "plumber",
        "secondary_trades": [],
        "city": "Tangier",
    }
]


class VerifyGroundingTests(unittest.TestCase):
    def test_allows_grounded_identity_phone_and_urls(self):
        response = (
            "Youssef: 0612345678. "
            "https://jak.ma/workers/worker-1, https://wa.me/212612345678, "
            "whatsapp://send?phone=212612345678"
        )

        ok, score, violations = verify_grounding(
            response, ["worker-1"], CANDIDATES
        )

        self.assertTrue(ok)
        self.assertEqual(score, 1.0)
        self.assertEqual(violations, [])

    def test_rejects_unknown_cited_id(self):
        ok, score, violations = verify_grounding(
            "A grounded response", ["worker-404"], CANDIDATES
        )

        self.assertFalse(ok)
        self.assertEqual(score, 0.0)
        self.assertEqual(violations[0]["type"], "cited_id_not_in_candidates")

    def test_rejects_fabricated_phone(self):
        ok, score, violations = verify_grounding(
            "Call 0699999999", ["worker-1"], CANDIDATES
        )

        self.assertFalse(ok)
        self.assertEqual(score, 0.0)
        self.assertIn("fabricated_phone_number", {v["type"] for v in violations})

    def test_rejects_trusted_domain_in_untrusted_host_or_query(self):
        response = (
            "https://jak.ma.evil.example/profile "
            "https://evil.example/?next=https://jak.ma"
        )

        ok, score, violations = verify_grounding(
            response, ["worker-1"], CANDIDATES
        )

        self.assertFalse(ok)
        self.assertEqual(score, 0.0)
        self.assertEqual(
            [v["type"] for v in violations],
            ["fabricated_url", "fabricated_url"],
        )

    def test_rejects_unapproved_whatsapp_action(self):
        ok, _, violations = verify_grounding(
            "whatsapp://evil?phone=212612345678", ["worker-1"], CANDIDATES
        )

        self.assertFalse(ok)
        self.assertEqual(violations[0]["type"], "fabricated_url")

    def test_applies_soft_penalty_to_suspect_proper_noun(self):
        ok, score, violations = verify_grounding(
            "contact Hamza for help", ["worker-1"], CANDIDATES
        )

        self.assertTrue(ok)
        self.assertAlmostEqual(score, 0.95)
        self.assertEqual(violations[0]["type"], "suspect_proper_noun")


if __name__ == "__main__":
    unittest.main()
