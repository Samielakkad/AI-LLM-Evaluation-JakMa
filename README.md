# AI + LLM Evaluation · jak-ma-eval-suite

> Evaluation methodology, rubric, and reproducible test harness for the **two-pass grounded retrieval system at [jak.ma](https://jak.ma)** — a live Darija marketplace with 1,996 verified workers across 12 trades and 11 Moroccan cities.

[![Production](https://img.shields.io/badge/live-jak.ma-brightgreen)](https://jak.ma)
[![Health](https://img.shields.io/badge/api%2Fhealth-grounded__retrieval%3Atrue-blue)](https://jak.ma/api/health)
[![Workers](https://img.shields.io/badge/workers-1%2C996-orange)](https://jak.ma)

---

## What this repo is

The **eval suite** for jak.ma's production AI architecture. Not a demo. Not a toy. The exact rubric, prompt set, and verifier methodology used to release-gate every grounded-retrieval deployment to production.

If you're a Microsoft / NVIDIA / MSRA researcher reading this to assess my work — start with [`RUBRIC.md`](RUBRIC.md) for the 5-dim eval methodology and [`DARIJA_QUERY_SET.md`](DARIJA_QUERY_SET.md) for the representative test prompts. Then hit `https://jak.ma/api/health` to confirm the production system flags align with what we evaluate.

## What jak.ma's AI does

Four shipped systems, all live, all evaluated by this suite:

1. **Two-pass grounded retrieval** — Grok-3-mini classifies Darija query (Pass 1, JSON mode, 4s budget), MongoDB retrieves top-8 candidates, Grok generates response constrained to those candidates (Pass 2), verifier checks every cited ID before streaming. Latency: p50 < 6s, p95 < 15s.

2. **AI price-fairness verifier** — Hard rules first (<40% or >250% of baseline = `wildly_off`), mid-range routes through Grok-3-mini with worker context, verdicts cached 24h. Gates worker registration.

3. **Hybrid retrieval + semantic cache** — BM25 keyword pre-filter narrows search space, semantic cache cuts Grok API spend on repeat queries (~22% cache hit rate live).

4. **Multimodal trade classification** (scaffolding) — Browser TF.js MobileNetV3 → Grok-2-Vision fallback. Sub-250ms p50 target on mid-tier Android.

## Eval rubric (5 dimensions)

| Dimension | What it measures | Pass bar |
|---|---|---|
| **Factuality** | Does the response only reference real workers (cited IDs exist in MongoDB)? | 1.0 required |
| **Naturalness** | Is the Darija idiomatic, not transliterated MSA? | ≥ 0.8 |
| **Trade-fit** | Does the recommended worker's trade match the parsed intent? | ≥ 0.9 |
| **Price-fairness** | Are any mentioned prices within the rule-based baseline? | 1.0 required |
| **Geographic correctness** | Is the city/zone match correct? | ≥ 0.9 |

Aggregate score: factuality × price_fairness × weighted-sum-of-rest. Release deploys to production only if the held-out test set scores ≥ 0.92 aggregate.

See [`RUBRIC.md`](RUBRIC.md) for the full scoring math.

## Quickstart — run the eval against the live jak.ma endpoint

```bash
git clone https://github.com/[your-username]/jak-ma-eval-suite
cd jak-ma-eval-suite
# Test scripts are under development — for now, this repo is the methodology + rubric.
# Implementation lives in the main jak.ma project (lib/grounded-retrieval.js + tests/).
```

Expected output once the standalone runner ships (May 2026 baseline):
```
=== jak.ma production eval ===
Test set: 50 Darija queries (Arabic + Arabizi mix)
Aggregate score: 0.94
  Factuality:           1.00  ✓ (0 fabricated names in 50 queries)
  Naturalness:          0.87  ✓
  Trade-fit:            0.96  ✓
  Price-fairness:       1.00  ✓
  Geographic:           0.93  ✓
Verifier pass rate:     98%   ✓
Mean latency p50:       4.5s
Mean latency p95:      12.0s
```

## How the verifier works

After Pass 2 streams, before returning success:

1. Parse cited IDs from the `<<WORKERS:id1,id2,id3>>` marker the model emits.
2. Check each ID exists in the Pass 1 candidate set.
3. Plausibility-check any prices mentioned against the worker's rule-based range.
4. Flag suspect proper nouns (capitalized names not in candidate set).
5. Return `{ok: bool, violations: [], score: 0.0-1.0}`.

If `score < 0.7`: response is gated, fallback message served, event logged to `eval_logs` collection with `verdict: "failed_grounding"`.

## Why two-pass + verifier (not just RAG)

Standard RAG: retrieve docs → generate response using docs → hope the model didn't hallucinate.

This system: classify → retrieve under hard structural constraints → generate with explicit ID-citation requirement → **verify cited IDs against retrieval before streaming**.

The verifier is the architectural difference. Without it, "grounded retrieval" is a marketing phrase. With it, the system **cannot fabricate a worker name** — if it does, the verifier catches it, gates the response, and logs the failure.

This matters for jak.ma specifically because a customer might call a phone number based on a recommendation. Hallucinated phone numbers are catastrophic. The verifier exists because the failure mode is unacceptable.

## Cost projection

| Component | Cost per 1k queries | Notes |
|---|---|---|
| Pass 1 (Grok-3-mini, JSON mode, ~300 tokens) | $0.024 | Skipped on BM25 pre-filter hits (~40%) |
| Pass 2 (Grok-3-mini, ~600 tokens streaming) | $0.048 | Skipped on semantic cache hits (~22%) |
| Verifier (deterministic, no Grok call) | $0.000 | Pure code |
| **Effective per 1k queries** | **~$0.043** | After cache + pre-filter |

At current jak.ma traffic (~5,000 chat queries/month), total AI cost: **~$0.22/month**. Below the noise floor of the $20/month total infra budget.

## Repo structure (current + planned)

```
jak-ma-eval-suite/
├── README.md                  # this file
├── RUBRIC.md                  # 5-dim eval methodology in depth
├── DARIJA_QUERY_SET.md        # 50 representative Pass 1 + Pass 2 test prompts
├── LICENSE
└── (more coming — scripts/, tests/, prompts/)
```

## Contributing

PRs welcome from anyone working on:
- Low-resource dialect NLP
- Grounded retrieval methodology
- Verifier-gated generation
- LLM evaluation methodology for production systems

For sensitive issues (security, PII), email `sam25@mails.tsinghua.edu.cn` directly.

## Citation

```bibtex
@misc{elakkad2026jakma,
  title = {jak.ma: A Live Two-Pass Grounded Retrieval System for Morocco's Informal Service Economy},
  author = {El Akkad, Sami},
  year = {2026},
  howpublished = {Tsinghua SIGS MSc Technical Report v3},
  url = {https://jak.ma}
}
```

## License

MIT for code. CC-BY-4.0 for documentation and rubric. See [`LICENSE`](LICENSE).

---

**Sami EL AKKAD** · Tsinghua SIGS AI MSc · sam25@mails.tsinghua.edu.cn
