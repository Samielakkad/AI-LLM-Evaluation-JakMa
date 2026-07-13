"""Deterministic grounding checks for jak.ma evaluation responses."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


PHONE_REGEX = re.compile(r"\b0[567]\d{8}\b")
URL_REGEX = re.compile(r"(?i)\b(?:https?://|whatsapp://)[^\s<>\"']+")
PROPER_NOUN_REGEX = re.compile(r"\b[A-Z][a-z]{2,}\b")
PRICE_REGEX = re.compile(
    r"(?<!\d)(?P<low>\d{1,3}(?:,\d{3})+|\d{2,5})"
    r"(?:\s*[-\u2013\u2014]\s*(?P<high>\d{1,3}(?:,\d{3})+|\d{2,5}))?"
    r"\s*(?P<currency>MAD|DH|درهم)(?!\w)",
    re.IGNORECASE,
)

ALLOWED_HTTP_HOSTS = frozenset({"jak.ma", "www.jak.ma", "wa.me"})
ALLOWED_WHATSAPP_ACTIONS = frozenset({"send"})
DARIJA_COMMON_TERMS = {
    "plumber",
    "electrician",
    "painter",
    "carpenter",
    "specialist",
    "professional",
    "available",
    "contact",
    "casablanca",
    "rabat",
    "tangier",
    "marrakech",
    "fes",
    "agadir",
    "oujda",
    "meknes",
    "sale",
    "tetouan",
}

_TRAILING_URL_PUNCTUATION = ".,!?;:)]}،؛"
_MINIMUM_BASELINE_FACTOR = 0.5
_MAXIMUM_BASELINE_FACTOR = 2.5


def _is_allowed_url(raw_url: str) -> bool:
    """Return whether a generated URL matches an explicitly allowed target."""
    url = raw_url.rstrip(_TRAILING_URL_PUNCTUATION)
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False

    scheme = parsed.scheme.lower()
    if scheme in {"http", "https"}:
        return host in ALLOWED_HTTP_HOSTS
    if scheme == "whatsapp":
        return host in ALLOWED_WHATSAPP_ACTIONS
    return False


def _price_violations(
    response_text: str,
    cited_ids: list[str],
    candidates: list[dict],
) -> list[dict]:
    candidates_by_id = {candidate["id"]: candidate for candidate in candidates}
    cited_price_ranges = [
        candidates_by_id[cited_id]["price_range"]
        for cited_id in cited_ids
        if cited_id in candidates_by_id
    ]
    violations = []

    for match in PRICE_REGEX.finditer(response_text):
        quoted_prices = [int(match.group("low").replace(",", ""))]
        if match.group("high"):
            quoted_prices.append(int(match.group("high").replace(",", "")))

        grounded = any(
            all(
                price_range["min"] * _MINIMUM_BASELINE_FACTOR
                <= quoted_price
                <= price_range["max"] * _MAXIMUM_BASELINE_FACTOR
                for quoted_price in quoted_prices
            )
            for price_range in cited_price_ranges
        )
        if not grounded:
            violations.append(
                {
                    "type": "price_outside_baseline",
                    "severity": "soft",
                    "detail": "quoted price is outside every cited candidate baseline",
                    "evidence": match.group(0),
                }
            )

    return violations


def verify_grounding(
    response_text: str,
    cited_ids: list[str],
    candidates: list[dict],
) -> tuple[bool, float, list[dict]]:
    """Check a response against the candidate set.

    Returns ``(ok, score, violations)``. Identity, phone, and URL failures are
    hard failures; suspect proper nouns apply the soft penalty from the public
    verifier specification.
    """
    violations: list[dict] = []
    score = 1.0
    hard_failure = False

    candidate_id_set = {candidate["id"] for candidate in candidates}
    candidate_phones = {
        candidate.get("phone", "")
        for candidate in candidates
        if candidate.get("phone")
    }
    candidate_names = {
        piece
        for candidate in candidates
        for piece in candidate["name"].split()
    }

    for cited_id in cited_ids:
        if cited_id not in candidate_id_set:
            violations.append(
                {
                    "type": "cited_id_not_in_candidates",
                    "severity": "hard",
                    "detail": cited_id,
                }
            )
            hard_failure = True

    for phone in PHONE_REGEX.findall(response_text):
        if phone not in candidate_phones:
            violations.append(
                {
                    "type": "fabricated_phone_number",
                    "severity": "hard",
                    "detail": phone,
                }
            )
            hard_failure = True

    for url in URL_REGEX.findall(response_text):
        if not _is_allowed_url(url):
            violations.append(
                {
                    "type": "fabricated_url",
                    "severity": "hard",
                    "detail": url.rstrip(_TRAILING_URL_PUNCTUATION),
                }
            )
            hard_failure = True

    price_violations = _price_violations(response_text, cited_ids, candidates)
    violations.extend(price_violations)
    score -= 0.15 * len(price_violations)

    for noun in PROPER_NOUN_REGEX.findall(response_text):
        if noun not in candidate_names and noun.lower() not in DARIJA_COMMON_TERMS:
            violations.append(
                {
                    "type": "suspect_proper_noun",
                    "severity": "soft",
                    "detail": noun,
                }
            )
            score -= 0.05

    if hard_failure:
        return False, 0.0, violations
    score = max(0.0, score)
    return score >= 0.7, score, violations
