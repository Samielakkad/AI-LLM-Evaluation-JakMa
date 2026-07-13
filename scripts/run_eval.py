#!/usr/bin/env python3
"""
run_eval.py — Run the jak.ma 5-dim eval against any OpenAI-compatible endpoint.

Usage:
    python scripts/run_eval.py \\
        --endpoint https://jak.ma/api/ai/chat \\
        --test-set data/sample_queries.jsonl \\
        --output results.json

The endpoint must accept:
    POST { "query": str, "conversation_id": str | null }
    Streaming SSE response with <<WORKERS:id1,id2,id3>> marker at end

This script:
    1. Sends each query in the test set
    2. Parses Pass 1 (if exposed) and Pass 2 outputs
    3. Scores against the 5-dim rubric in RUBRIC.md
    4. Runs the deterministic grounding verifier (VERIFIER_SPEC.md §3-§4)
    5. Records latency p50/p95
    6. Outputs aggregate score + per-dimension breakdown

Dependencies:
    pip install httpx tqdm pyarrow

Sami EL AKKAD · sam25@mails.tsinghua.edu.cn
"""

import argparse
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

if __package__:
    from .candidate_data import CandidateDataError, load_candidate_sets
    from .verifier import verify_grounding
else:
    from candidate_data import CandidateDataError, load_candidate_sets
    from verifier import verify_grounding

try:
    import httpx
    from tqdm import tqdm
except ImportError:
    print("Missing dependencies. Install with: pip install httpx tqdm", file=sys.stderr)
    sys.exit(1)


# -------------------------------------------------------------------
# Data classes
# -------------------------------------------------------------------

@dataclass
class QueryResult:
    id: str
    query: str
    expected: dict
    response_text: str = ""
    cited_ids: list = field(default_factory=list)
    pass1_result: dict = field(default_factory=dict)
    duration_ms: float = 0
    error: Optional[str] = None
    # Per-dimension scores (filled by scorer)
    factuality: float = 0
    naturalness: float = 0
    trade_fit: float = 0
    price_fairness: float = 0
    geographic: float = 0
    verifier_passed: bool = False
    aggregate: float = 0


# -------------------------------------------------------------------
# Endpoint client
# -------------------------------------------------------------------

WORKERS_MARKER = re.compile(r"<<WORKERS:([^>]*)>>")


def call_endpoint(endpoint: str, query: str, conversation_id: Optional[str] = None,
                  timeout: float = 30.0) -> tuple[str, list[str], dict, float]:
    """Returns (response_text, cited_ids, pass1_result, duration_ms)."""
    started = time.monotonic()
    payload = {"query": query, "conversation_id": conversation_id}

    with httpx.Client(timeout=timeout) as client:
        try:
            r = client.post(endpoint, json=payload)
            r.raise_for_status()
            text = r.text
        except httpx.HTTPError as e:
            raise RuntimeError(f"Endpoint error: {e}")

    duration_ms = (time.monotonic() - started) * 1000

    marker = WORKERS_MARKER.search(text)
    cited_ids = []
    if marker:
        ids_raw = marker.group(1).strip()
        cited_ids = [s.strip() for s in ids_raw.split(",") if s.strip()]
        text = text[:marker.start()].strip()

    # Try to extract Pass 1 from a JSON envelope if the endpoint exposes it
    pass1_result = {}
    pass1_match = re.search(r'"pass1":\s*({[^}]+})', r.text)
    if pass1_match:
        try:
            pass1_result = json.loads(pass1_match.group(1))
        except json.JSONDecodeError:
            pass

    return text, cited_ids, pass1_result, duration_ms


# -------------------------------------------------------------------
# 5-dim scorer
# -------------------------------------------------------------------

def score_response(result: QueryResult, candidates: list[dict] = None) -> QueryResult:
    """Scores against the 5-dim rubric. Some dimensions require human review
    (naturalness in particular). This automated pass scores what it can; flag
    the rest for manual review.
    """
    candidates = candidates or []

    # Factuality: did the verifier pass?
    ok, _score, violations = verify_grounding(
        result.response_text, result.cited_ids, candidates
    )
    result.factuality = 1.0 if ok else 0.0
    result.verifier_passed = ok

    # Trade-fit: do cited workers have the expected trade?
    expected_trades = set(result.expected.get("trades", []))
    if expected_trades and result.cited_ids:
        matching = 0
        for cid in result.cited_ids:
            for c in candidates:
                if c["id"] == cid and (c.get("trade") in expected_trades or
                                       any(t in expected_trades for t in c.get("secondary_trades", []))):
                    matching += 1
                    break
        result.trade_fit = matching / len(result.cited_ids) if result.cited_ids else 0
    else:
        # Off-topic / ambiguous queries: pass if we returned no IDs
        result.trade_fit = 1.0 if not result.cited_ids else 0.5

    # Geographic: do cited workers match expected city?
    expected_city = result.expected.get("city")
    if expected_city and result.cited_ids and candidates:
        matching = sum(1 for cid in result.cited_ids
                       for c in candidates if c["id"] == cid and c.get("city") == expected_city)
        result.geographic = matching / len(result.cited_ids) if result.cited_ids else 0
    else:
        result.geographic = 1.0

    # Price-fairness: any out-of-baseline quote is a non-negotiable failure.
    has_price_violation = any(
        violation.get("type") == "price_outside_baseline"
        for violation in violations
    )
    result.price_fairness = 0.0 if has_price_violation else 1.0

    # Naturalness: stub — set to 0.8 baseline. Manual review for finer grain.
    result.naturalness = 0.8

    # Aggregate
    result.aggregate = max(
        0.0,
        result.factuality * result.price_fairness * (
            0.35 * result.trade_fit
            + 0.30 * result.naturalness
            + 0.20 * result.geographic
            + 0.15 * (1.0 if result.verifier_passed else 0.0)
        )
    )

    return result


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run jak.ma 5-dim eval against any OpenAI-compatible endpoint")
    parser.add_argument("--endpoint", required=True, help="The chat endpoint URL")
    parser.add_argument("--test-set", required=True, help="Path to JSONL test set")
    parser.add_argument(
        "--candidates",
        required=True,
        help="JSON object mapping each evaluated query ID to its candidate array",
    )
    parser.add_argument("--output", default="results.json", help="Output JSON file")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries")
    args = parser.parse_args()

    test_path = Path(args.test_set)
    if not test_path.exists():
        print(f"Test set not found: {test_path}", file=sys.stderr)
        sys.exit(1)

    queries = []
    with test_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            queries.append(QueryResult(id=row["id"], query=row["query"], expected=row.get("expected", {})))

    if args.limit:
        queries = queries[:args.limit]

    try:
        candidate_sets = load_candidate_sets(
            args.candidates, [query.id for query in queries]
        )
    except CandidateDataError as error:
        parser.error(str(error))

    print(f"Running {len(queries)} queries against {args.endpoint}")
    print()

    results = []
    latencies = []
    for q in tqdm(queries):
        try:
            response_text, cited_ids, pass1, duration_ms = call_endpoint(args.endpoint, q.query)
            q.response_text = response_text
            q.cited_ids = cited_ids
            q.pass1_result = pass1
            q.duration_ms = duration_ms
            latencies.append(duration_ms)
        except Exception as e:
            q.error = str(e)
            results.append(q)
            continue

        q = score_response(q, candidates=candidate_sets[q.id])
        results.append(q)

    # Aggregate
    successful = [r for r in results if not r.error]
    if not successful:
        print("No successful queries — endpoint unreachable?")
        sys.exit(1)

    factuality = statistics.mean(r.factuality for r in successful)
    naturalness = statistics.mean(r.naturalness for r in successful)
    trade_fit = statistics.mean(r.trade_fit for r in successful)
    price_fairness = statistics.mean(r.price_fairness for r in successful)
    geographic = statistics.mean(r.geographic for r in successful)
    aggregate = statistics.mean(r.aggregate for r in successful)
    verifier_pass_rate = sum(1 for r in successful if r.verifier_passed) / len(successful)

    summary = {
        "endpoint": args.endpoint,
        "n_queries": len(queries),
        "n_successful": len(successful),
        "aggregate": round(aggregate, 3),
        "dimensions": {
            "factuality": round(factuality, 3),
            "naturalness": round(naturalness, 3),
            "trade_fit": round(trade_fit, 3),
            "price_fairness": round(price_fairness, 3),
            "geographic": round(geographic, 3),
        },
        "verifier_pass_rate": round(verifier_pass_rate, 3),
        "latency": {
            "p50_ms": round(statistics.median(latencies), 1) if latencies else None,
            "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 1) if latencies else None,
            "mean_ms": round(statistics.mean(latencies), 1) if latencies else None,
        },
        "passed_release_gate": aggregate >= 0.92,
        "results": [asdict(r) for r in results],
    }

    with open(args.output, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print()
    print(f"=== jak.ma 5-dim eval summary ===")
    print(f"  Aggregate:           {summary['aggregate']}")
    print(f"  Factuality:          {summary['dimensions']['factuality']}")
    print(f"  Naturalness:         {summary['dimensions']['naturalness']}")
    print(f"  Trade-fit:           {summary['dimensions']['trade_fit']}")
    print(f"  Price-fairness:      {summary['dimensions']['price_fairness']}")
    print(f"  Geographic:          {summary['dimensions']['geographic']}")
    print(f"  Verifier pass rate:  {summary['verifier_pass_rate']}")
    print(f"  Latency p50/p95:     {summary['latency']['p50_ms']}ms / {summary['latency']['p95_ms']}ms")
    print(f"  Release gate:        {'PASS' if summary['passed_release_gate'] else 'FAIL'}")
    print()
    print(f"Detailed results written to: {args.output}")


if __name__ == "__main__":
    main()
