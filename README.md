# JakMa Evaluation Suite

[![CI](https://github.com/Samielakkad/AI-LLM-Evaluation-JakMa/actions/workflows/ci.yml/badge.svg)](https://github.com/Samielakkad/AI-LLM-Evaluation-JakMa/actions/workflows/ci.yml)

Evaluation and verification tools for a grounded-retrieval response pipeline. The repository contains a five-dimension rubric, 52 public Darija/Arabizi query cases, endpoint-response parsers, candidate validation, and deterministic grounding checks.

It does not contain private production candidates or evaluation logs, and it does not claim a current production score.

## What is included

| Part | Purpose |
| --- | --- |
| [`data/sample_queries.jsonl`](data/sample_queries.jsonl) | 52 public service-query cases with expected intent fields |
| [`scripts/response_parser.py`](scripts/response_parser.py) | Parses documented JSON, SSE, and terminal worker markers |
| [`scripts/candidate_data.py`](scripts/candidate_data.py) | Validates per-query candidate snapshots before scoring |
| [`scripts/verifier.py`](scripts/verifier.py) | Checks cited IDs, phone numbers, URLs, names, and price baselines |
| [`scripts/run_eval.py`](scripts/run_eval.py) | Calls an endpoint and writes per-query and aggregate output |
| [`RUBRIC.md`](RUBRIC.md) | Defines factuality, naturalness, trade fit, price fairness, and geography |

## Run the offline checks

```bash
python -m pip install -r requirements-dev.txt
ruff check scripts tests
python -m unittest discover -s tests -v
```

The current suite has 34 offline tests. They cover data validation, transport parsing, scoring, and adversarial verifier cases without contacting a live endpoint.

## Evaluate an endpoint

```bash
python -m pip install -r requirements.txt

python scripts/run_eval.py \
  --endpoint https://example.com/api/chat \
  --test-set data/sample_queries.jsonl \
  --candidates /secure/path/candidates.json \
  --output results.json
```

Candidate data is required because factuality, trade fit, geography, and price checks must compare a response with the records that were actually available for that query. Keep real names and contact details outside the repository.

Naturalness needs a Darija-speaking reviewer. Without reviewer scores, the runner records `naturalness`, `aggregate`, and `passed_release_gate` as `null` rather than inventing a default score. To complete the rubric, provide a JSON object with one 0–1 score per evaluated query:

```json
{
  "q001": 0.9,
  "q002": 0.8
}
```

```bash
python scripts/run_eval.py \
  --endpoint https://example.com/api/chat \
  --test-set data/sample_queries.jsonl \
  --candidates /secure/path/candidates.json \
  --naturalness-scores /secure/path/naturalness.json \
  --output results.json
```

The reviewer file must contain every query included in the run. The output keeps the endpoint, per-query results, dimension values, verifier pass rate, and observed request latency so results can be audited later.

## Evidence boundary

- The public query file is a transparent regression set, not a hidden benchmark.
- The offline tests prove parser and verifier behavior, not model quality.
- Endpoint scores depend on the exact endpoint version, candidate snapshot, query set, reviewer scores, and run time.
- Historical operational numbers are not presented as current results without the underlying output artifact.

## License

All rights reserved. Public visibility grants review and reference access only; see [`LICENSE`](LICENSE).
