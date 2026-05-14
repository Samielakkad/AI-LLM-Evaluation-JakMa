# Evaluation Rubric — jak.ma Two-Pass Grounded Retrieval

This rubric is used to gate every production deployment of jak.ma's AI architecture. A release ships only if the aggregate score on the held-out test set exceeds **0.92**.

---

## The 5 dimensions

### 1. Factuality — non-negotiable (1.0 required)

**Question:** Does the response reference only workers that exist in MongoDB?

**Scoring:** Binary. Any cited worker ID that doesn't exist in the candidate set returned by `retrieveCandidates()` is a failure. The verifier (`verifyGrounding()` in `lib/grounded-retrieval.js`) catches this automatically.

**Failure modes:**
- Fabricated worker name in the response
- Fabricated phone number (catastrophic — customer might call it)
- Cited ID outside the Pass-1 candidate set

### 2. Naturalness — weighted (≥ 0.8)

**Question:** Is the response idiomatic Darija, not transliterated Modern Standard Arabic (MSA)?

**Scoring:** 0.0-1.0 by a native-Darija reviewer. Rubric anchors:
- 1.0 = "This is how my neighbor would explain it."
- 0.8 = "Idiomatic but slightly bookish."
- 0.6 = "Comprehensible but sounds like translated MSA."
- 0.4 = "Mixed code-switching feels forced."
- 0.0 = "Pure MSA, not Darija."

**Bonus:** Latin-script Darija (Arabizi) handled gracefully gets +0.1.

### 3. Trade-fit — weighted (≥ 0.9)

**Question:** Does the recommended worker's primary or secondary trade match the parsed intent?

**Scoring:** 
- 1.0 = primary category matches
- 0.7 = secondary category matches (multi-trade worker)
- 0.4 = adjacent trade (e.g., plumber for tiling work) with explicit reasoning in response
- 0.0 = wrong trade entirely

### 4. Price-fairness — non-negotiable (1.0 required)

**Question:** Are any prices mentioned in the response within the rule-based baseline range for that worker?

**Scoring:** Binary. Cross-checked against `scripts/price-engine.js` output. The fairness verifier (`lib/price-fairness.js`) catches violations automatically.

### 5. Geographic correctness — weighted (≥ 0.9)

**Question:** Is the city/zone match correct?

**Scoring:**
- 1.0 = exact city match
- 0.8 = adjacent city in same region (e.g., Salé suggested for Rabat query — acceptable for outskirts)
- 0.5 = same region but different city
- 0.0 = wrong city

---

## Aggregate score formula

```
aggregate = max(0, factuality × price_fairness × (
    0.35 × trade_fit +
    0.30 × naturalness +
    0.20 × geographic +
    0.15 × verifier_pass_rate
))
```

The multiplicative factuality × price_fairness factor enforces the non-negotiable bar: if either is below 1.0, aggregate is 0. The remaining 4 dimensions trade off against each other.

**Release gate:** aggregate ≥ 0.92 on a held-out test set of 50 representative Darija queries (see `DARIJA_QUERY_SET.md`).

---

## Verifier pass rate (the meta-dimension)

The verifier is the architectural safeguard. It runs after Pass 2 and before streaming success. A response that fails the verifier is gated, replaced with a safe fallback, and logged to `eval_logs` with `verdict: "failed_grounding"`.

Verifier pass rate is measured as: `passes / total_queries`. The target is ≥ 95% in production.

Historical baselines:
- May 2026 (post-grounded-retrieval rollout): 98%
- Reference legacy handler (open Grok): 41%
- Worst case in development: 71%

---

## What this rubric is NOT

- Not a benchmark for Darija-LLM-general (use the open Darija benchmarks for that)
- Not a measure of conversational quality outside service-discovery context
- Not a substitute for human evaluation — the rubric assumes a native-Darija reviewer is in the loop for dimensions 2 and 3

---

## Running the rubric

```bash
python scripts/run_eval.py \
    --endpoint https://jak.ma/api/ai/chat \
    --test-set data/sample_queries.jsonl \
    --rubric RUBRIC.md \
    --output results.json
```

Results format:
```json
{
  "endpoint": "https://jak.ma/api/ai/chat",
  "n_queries": 50,
  "aggregate": 0.94,
  "dimensions": {
    "factuality": 1.00,
    "naturalness": 0.87,
    "trade_fit": 0.96,
    "price_fairness": 1.00,
    "geographic": 0.93
  },
  "verifier_pass_rate": 0.98,
  "latency": { "p50_ms": 4500, "p95_ms": 12000 },
  "passed_release_gate": true
}
```

---

**Last updated:** May 2026 · Sami EL AKKAD · sam25@mails.tsinghua.edu.cn
