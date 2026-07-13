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
        "price_range": {"min": 200, "max": 300, "unit": "day"},
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

    def test_allows_point_and_range_prices_inside_baseline_envelope(self):
        ok, score, violations = verify_grounding(
            "Youssef: 200 MAD or 210-320 DH", ["worker-1"], CANDIDATES
        )

        self.assertTrue(ok)
        self.assertEqual(score, 1.0)
        self.assertEqual(violations, [])

    def test_flags_low_high_and_comma_separated_prices(self):
        ok, score, violations = verify_grounding(
            "offers: 50 درهم and 50,000 MAD", ["worker-1"], CANDIDATES
        )

        self.assertTrue(ok)
        self.assertAlmostEqual(score, 0.7)
        self.assertEqual(
            [violation["type"] for violation in violations],
            ["price_outside_baseline", "price_outside_baseline"],
        )
        self.assertEqual(
            [violation["evidence"] for violation in violations],
            ["50 درهم", "50,000 MAD"],
        )

    def test_flags_range_when_one_endpoint_is_outside_baseline(self):
        ok, score, violations = verify_grounding(
            "range: 200-900 MAD", ["worker-1"], CANDIDATES
        )

        self.assertTrue(ok)
        self.assertAlmostEqual(score, 0.85)
        self.assertEqual(violations[0]["type"], "price_outside_baseline")

    def test_flags_price_without_a_cited_candidate_baseline(self):
        ok, score, violations = verify_grounding("price: 250 MAD", [], CANDIDATES)

        self.assertTrue(ok)
        self.assertAlmostEqual(score, 0.85)
        self.assertEqual(violations[0]["type"], "price_outside_baseline")


if __name__ == "__main__":
    unittest.main()
