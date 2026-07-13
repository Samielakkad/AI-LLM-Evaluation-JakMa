"""Load and validate per-query candidate sets for the eval runner."""

from __future__ import annotations

import json
from pathlib import Path


class CandidateDataError(ValueError):
    """Raised when a candidate-set file cannot be evaluated safely."""


def _require_nonempty_string(candidate: dict, field: str, location: str) -> str:
    value = candidate.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CandidateDataError(f"{location}.{field} must be a non-empty string")
    return value


def _validate_candidate(raw_candidate: object, location: str) -> dict:
    if not isinstance(raw_candidate, dict):
        raise CandidateDataError(f"{location} must be an object")

    candidate = dict(raw_candidate)
    for field in ("id", "name", "trade", "city"):
        candidate[field] = _require_nonempty_string(candidate, field, location).strip()

    secondary_trades = candidate.get("secondary_trades", [])
    if not isinstance(secondary_trades, list) or not all(
        isinstance(trade, str) and trade.strip() for trade in secondary_trades
    ):
        raise CandidateDataError(
            f"{location}.secondary_trades must be an array of non-empty strings"
        )
    candidate["secondary_trades"] = [trade.strip() for trade in secondary_trades]

    phone = candidate.get("phone")
    if phone is not None and not isinstance(phone, str):
        raise CandidateDataError(f"{location}.phone must be a string when present")
    if phone is not None:
        candidate["phone"] = phone.strip()

    return candidate


def load_candidate_sets(
    path: str | Path,
    required_query_ids: list[str],
) -> dict[str, list[dict]]:
    """Load ``{query_id: [candidate, ...]}`` JSON and validate used entries."""
    candidate_path = Path(path)
    try:
        raw_data = json.loads(candidate_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CandidateDataError(
            f"could not read candidate file {candidate_path}: {error}"
        ) from error
    except json.JSONDecodeError as error:
        raise CandidateDataError(
            f"candidate file {candidate_path} is not valid JSON: {error}"
        ) from error

    if not isinstance(raw_data, dict):
        raise CandidateDataError(
            "candidate file must be a JSON object mapping query IDs to arrays"
        )

    missing_query_ids = [
        query_id for query_id in required_query_ids if query_id not in raw_data
    ]
    if missing_query_ids:
        missing = ", ".join(missing_query_ids)
        raise CandidateDataError(f"candidate file is missing query IDs: {missing}")

    candidate_sets: dict[str, list[dict]] = {}
    for query_id in required_query_ids:
        raw_candidates = raw_data[query_id]
        if not isinstance(raw_candidates, list):
            raise CandidateDataError(f"candidates.{query_id} must be an array")

        candidates = [
            _validate_candidate(candidate, f"candidates.{query_id}[{index}]")
            for index, candidate in enumerate(raw_candidates)
        ]
        candidate_ids = [candidate["id"] for candidate in candidates]
        duplicate_ids = sorted(
            candidate_id
            for candidate_id in set(candidate_ids)
            if candidate_ids.count(candidate_id) > 1
        )
        if duplicate_ids:
            duplicates = ", ".join(duplicate_ids)
            raise CandidateDataError(
                f"candidates.{query_id} contains duplicate IDs: {duplicates}"
            )
        candidate_sets[query_id] = candidates

    return candidate_sets
