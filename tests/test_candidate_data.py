import json
import tempfile
import unittest
from pathlib import Path

from scripts.candidate_data import CandidateDataError, load_candidate_sets


def candidate(candidate_id="worker-1", **overrides):
    value = {
        "id": candidate_id,
        "name": "Youssef Amrani",
        "trade": "plumber",
        "secondary_trades": [],
        "city": "Tangier",
        "phone": "0612345678",
        "price_range": {"min": 200, "max": 300, "unit": "day"},
    }
    value.update(overrides)
    return value


class LoadCandidateSetsTests(unittest.TestCase):
    def load(self, payload, query_ids):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return load_candidate_sets(path, query_ids)

    def test_loads_valid_per_query_candidates_and_ignores_extra_sets(self):
        payload = {
            "q001": [candidate()],
            "q-not-in-smoke-run": [],
        }

        loaded = self.load(payload, ["q001"])

        self.assertEqual(loaded["q001"][0]["id"], "worker-1")
        self.assertEqual(loaded["q001"][0]["secondary_trades"], [])
        self.assertNotIn("q-not-in-smoke-run", loaded)

    def test_defaults_secondary_trades_to_empty_list(self):
        worker = candidate()
        del worker["secondary_trades"]

        loaded = self.load({"q001": [worker]}, ["q001"])

        self.assertEqual(loaded["q001"][0]["secondary_trades"], [])

    def test_normalizes_candidate_identity_and_label_whitespace(self):
        worker = candidate(
            candidate_id=" worker-1 ",
            name=" Youssef Amrani ",
            trade=" plumber ",
            city=" Tangier ",
            secondary_trades=[" electrician "],
            phone=" 0612345678 ",
        )

        loaded = self.load({"q001": [worker]}, ["q001"])["q001"][0]

        self.assertEqual(loaded["id"], "worker-1")
        self.assertEqual(loaded["name"], "Youssef Amrani")
        self.assertEqual(loaded["trade"], "plumber")
        self.assertEqual(loaded["city"], "Tangier")
        self.assertEqual(loaded["secondary_trades"], ["electrician"])
        self.assertEqual(loaded["phone"], "0612345678")

    def test_rejects_missing_query_set(self):
        with self.assertRaisesRegex(CandidateDataError, "missing query IDs: q002"):
            self.load({"q001": []}, ["q001", "q002"])

    def test_rejects_duplicate_candidate_ids_within_query(self):
        payload = {"q001": [candidate(), candidate()]}

        with self.assertRaisesRegex(CandidateDataError, "duplicate IDs: worker-1"):
            self.load(payload, ["q001"])

    def test_rejects_invalid_candidate_field_type(self):
        payload = {"q001": [candidate(city=None)]}

        with self.assertRaisesRegex(
            CandidateDataError, r"candidates\.q001\[0\]\.city"
        ):
            self.load(payload, ["q001"])

    def test_rejects_inverted_price_range(self):
        payload = {
            "q001": [
                candidate(price_range={"min": 400, "max": 200, "unit": "day"})
            ]
        }

        with self.assertRaisesRegex(CandidateDataError, "min must not exceed"):
            self.load(payload, ["q001"])

    def test_rejects_missing_price_unit(self):
        payload = {
            "q001": [candidate(price_range={"min": 200, "max": 300})]
        }

        with self.assertRaisesRegex(CandidateDataError, "unit must be"):
            self.load(payload, ["q001"])

    def test_rejects_non_finite_price_range(self):
        payload = {
            "q001": [
                candidate(
                    price_range={"min": 200, "max": float("nan"), "unit": "day"}
                )
            ]
        }

        with self.assertRaisesRegex(CandidateDataError, "max must be finite"):
            self.load(payload, ["q001"])

    def test_rejects_non_mapping_document(self):
        with self.assertRaisesRegex(CandidateDataError, "must be a JSON object"):
            self.load([], ["q001"])


if __name__ == "__main__":
    unittest.main()
