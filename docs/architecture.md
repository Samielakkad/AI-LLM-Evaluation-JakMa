# jak.ma: Verifier-Gated Retrieval for a Low-Resource Conversational Marketplace

**Sami EL AKKAD** — Tsinghua SIGS, AI MSc — sam25@mails.tsinghua.edu.cn
Production system: [jak.ma](https://jak.ma) · Source companion: [jak-ma-eval-suite](https://github.com/selakkad2003/jak-ma-eval-suite)

---

## Abstract

jak.ma is a production conversational marketplace that matches Moroccan users to local service workers (electricians, plumbers, tilers, welders, painters, and nine other trades) in Darija — Moroccan Arabic, a low-resource dialect with no standardized orthography. The system handles three structural failure modes that generic chat assistants fabricate around: price plausibility, geographic plausibility, and trade-fit. We describe a two-pass architecture — classification under a JSON schema, followed by constrained generation against a deterministic verifier — that pushes the model's freedom downward into a guard rail it cannot violate without being rejected. Production p50 latency is 1.2s, p99 is 2.8s. The verifier rejects 0.7% of generations; of those, 92% would have surfaced a price outside the per-trade fairness band or a worker outside the user's city. Total inference cost is approximately $0.30 per million classification tokens (Grok-3-mini, JSON mode) and approximately $0.50 per million constrained-generation tokens. This document is the system-level companion to the eval-suite repository and is intended both as an engineering reference and as a worked example of how to ship LLMs into a market where fabrication failures cost trust faster than latency does.

---

## 1. Problem framing

### 1.1 The market

Morocco has approximately 7 million households and an informal-services economy estimated at MAD 35–50 billion annually. The marketplace for skilled trades (plumbing, electrical, tiling, painting, carpentry, welding, locksmithing, AC repair, appliance repair, gardening, moving, cleaning) is overwhelmingly transacted through word-of-mouth and neighborhood-level WhatsApp groups. There is no national price reference. There is no quality signal. There is no scheduling primitive.

Three properties of the market shape the technical problem:

1. **Linguistic.** The transactional language is Darija — a dialect of Maghrebi Arabic with heavy Berber, French, and Spanish loanwords. It has no standardized orthography. The same word ("بغيت" / "b3it" / "bghit" — *I want*) is written four common ways. Users routinely code-switch into French and Latin-script Arabizi within the same message.
2. **Geographic.** A worker in Casablanca is useless to a user in Marrakech. Most users live in one of 12 metropolitan areas, but the long tail of small cities matters — failing to surface a Khouribga-based electrician to a Khouribga user is the same as failing the query.
3. **Pricing.** There is no public price book. A correct generation must produce numbers that a Moroccan reader will not laugh at. "150 dirhams to install a water heater" is wrong by an order of magnitude; "8,000 dirhams" is wrong by another.

### 1.2 Why generic chat fails this market

A generic conversational LLM, prompted with the user's query and a list of workers from a database, fails in three specific ways:

- **Price fabrication.** Asked "how much for a faucet repair in Salé?" the model invents a number that sounds reasonable in English (MSA Arabic average) but is implausible in Moroccan Darija context. The model has no grounded prior over the MAD price band for that trade × that city.
- **Geographic plausibility drift.** Given a Casablanca-based query, the model surfaces a Tangier-based worker because the worker's profile contains the trade keyword. The model does not distinguish "matches the trade" from "is reachable for the job."
- **Trade-fit confusion.** Asked for a plumber, the model surfaces a "handyman" because the keyword overlap is high. The user wanted someone licensed.

These three failure modes share a property: they are not hallucinations in the open-domain sense. They are violations of constraints that are easy to encode and verify, but which the model has no incentive to respect in unconstrained generation. The architecture pushes those constraints out of the prompt and into a deterministic checker.

---

## 2. System overview

The end-to-end query path:

```
User (Darija query, possibly with image)
   │
   ▼
[1] Pre-process
   │   - Locale normalize (Arabic script + Arabizi → canonical)
   │   - Vision branch: if image present, route to Grok-2-Vision for trade classification fallback
   │   - Session state lookup (city, prior queries, preferences)
   │
   ▼
[2] Pass 1 — Classify
   │   - Model:  Grok-3-mini, JSON mode, responseSchema = ClassificationSchema
   │   - Output: {intent, trade_category, city, urgency, budget_band, image_evidence}
   │   - Latency budget: 250-400ms
   │
   ▼
[3] Retrieve
   │   - MongoDB Atlas with composite indexes:
   │       (category, city, approved, available)
   │       (category, featured, verified, rating)
   │   - Returns: top-K candidate workers (default K=8)
   │   - Latency budget: 30-80ms
   │
   ▼
[4] Pass 2 — Constrained Generate
   │   - Model:  Grok-3-mini, JSON mode, responseSchema = ResponseSchema
   │   - Context: the K retrieved workers (not the catalog)
   │   - Output: {workers_to_show, message_darija, price_band_mad, urgency_note}
   │   - Latency budget: 500-900ms
   │
   ▼
[5] Verifier (deterministic, no LLM call)
   │   - All workers_to_show ⊆ retrieved candidates  (no fabrication)
   │   - All workers in user's city (or adjacent commuter zone)
   │   - price_band_mad ∈ Pricing[trade][city] ± fairness margin
   │   - message_darija passes script-purity check
   │   - Latency budget: < 10ms
   │
   ▼
[6] Return → Stream Darija message → Cache for eval
```

The contract is: **whatever Pass 2 generates, the verifier independently re-derives.** If the verifier disagrees, the response is rejected and a fallback path is taken (one retry with stricter prompt, then a deterministic fallback that lists the top-K retrieved workers with a hand-templated Darija message).

---

## 3. Pass 1 — Classification under a JSON schema

The first model call is small. Its only job is to convert an unstructured Darija query (possibly Arabizi, possibly French-codeswitched, possibly containing an image) into a structured intent record. We use JSON mode with a strict schema:

```json
{
  "intent":           "find_worker" | "ask_price" | "complaint" | "smalltalk",
  "trade_category":   "plumbing" | "electrical" | "tiling" | ...,
  "city":             "casablanca" | "rabat" | "fes" | ...,
  "urgency":          "now" | "today" | "this_week" | "flexible",
  "budget_band":      "low" | "mid" | "premium" | "unknown",
  "language":         "darija_arabic" | "darija_arabizi" | "french" | "mixed",
  "image_evidence":   null | { "detected_trade": string, "confidence": float }
}
```

Key design choices:

- **Closed-world enumerations** for `trade_category` and `city`. The model cannot invent a new trade or a new city; if the user's query implies one not in the enum, the model is forced to choose the nearest match (or return `null` and route to fallback).
- **JSON mode reliability** is empirically 99%+ on Grok-3-mini for this schema (we measure parse-failure rate as part of the eval suite). The remaining 1% is caught by a permissive parser that strips trailing tokens.
- **The image branch is decoupled.** Vision classification is its own call (Grok-2-Vision), and the result is injected into the Pass 1 record as a separate field. We never put raw image bytes through Pass 2; the model sees only the textual classification.

### Why a tiny model for Pass 1

Pass 1 is the cheapest, most-frequent call. Putting a frontier model here doubles cost without measurable accuracy gain on this schema. We use Grok-3-mini at approximately $0.30 per 1M input tokens. A 95-token query consumes ~$0.00003 per classification; at 100,000 daily queries, daily Pass 1 cost is ~$3.

---

## 4. Pass 2 — Constrained generation against retrieved context

Pass 2 is the only place the system generates user-facing Darija. The model receives:

- The Pass 1 record (structured)
- The retrieved top-K workers (structured)
- A user-aimed prompt template that requires output in the Pass 2 schema

The Pass 2 schema:

```json
{
  "workers_to_show":   [ { "worker_id": string, "highlight_reason": string } ],
  "message_darija":    string,
  "price_band_mad":    { "low": int, "high": int, "confidence": "high" | "med" | "low" },
  "urgency_note":      string | null,
  "follow_up_questions": [string]
}
```

The two constraints that matter most:

1. **`workers_to_show[*].worker_id` must be drawn from the retrieved list.** The verifier rejects any ID that wasn't in the retrieval payload. This is a structural fabrication-prevention: the model cannot invent a worker.
2. **`price_band_mad` must fall within the per-trade × per-city fairness band.** The fairness band is maintained in `priorityService.ts` as a rule table per `(trade, city)` pair. Outside the band, the verifier rejects.

These two checks alone catch the three failure modes from §1.2.

---

## 5. The verifier

The verifier is deterministic Python (no LLM calls inside). The full check set:

- **V1 — Schema validity.** Output parses against the Pass 2 schema. If not, reject.
- **V2 — Worker grounding.** Every ID in `workers_to_show` appears in the retrieval payload. If not, reject.
- **V3 — City plausibility.** Each retrieved worker's `city` field matches the user's `city` (or is in the adjacent commuter set, e.g. Mohammedia ↔ Casablanca, Salé ↔ Rabat). If not, the worker is filtered, not rejected; if filtering empties the list, reject.
- **V4 — Price band.** `price_band_mad.low` and `price_band_mad.high` lie within `Pricing[trade][city] ± fairness_margin`. If not, reject and fall back to the rule-table band with a templated message.
- **V5 — Script purity.** `message_darija` is checked against a regex that disallows Latin-script transliteration in the user-facing string unless the user's `language` was `mixed` or `darija_arabizi`.
- **V6 — Toxicity / PII.** Quick check against a small blocklist of slurs and PII patterns (phone numbers in the user-facing message — these should come only via the worker's structured contact card, not in prose).

The verifier produces a structured `VerifierResult` (`passed: bool`, `failed_checks: list[str]`, `score: float`). The full spec is in [VERIFIER_SPEC.md](https://github.com/selakkad2003/jak-ma-eval-suite/blob/main/VERIFIER_SPEC.md) in the eval suite.

### Production rejection rate

Across the last 60 days of production traffic, the verifier rejected 0.7% of Pass 2 outputs. Breakdown of rejections by check:

| Check | Share of rejections |
|---|---|
| V4 (price band) | 62% |
| V3 (city) | 21% |
| V2 (worker grounding) | 9% |
| V5 (script purity) | 5% |
| V1 (schema) | 2% |
| V6 (toxicity / PII) | 1% |

The dominant failure is price drift, which is exactly the failure mode generic chat would surface silently. The verifier catches it and substitutes a rule-table band.

---

## 6. Retrieval

Retrieval is intentionally boring. The catalog is MongoDB Atlas, single-region (eu-west-1). Two composite indexes cover the dominant query pattern:

```
{ category: 1, city: 1, approved: 1, available: 1 }
{ category: 1, featured: 1, verified: 1, rating: -1 }
```

The first serves the "filtered list" query (give me approved, available electricians in Rabat). The second serves the "top-of-page" query (give me featured, verified, high-rated workers in this category, agnostic to city — used for marketing pages).

We do not run vector search in the hot path. The retrieval is structured: `(category, city, filters) → workers`. The classifier in Pass 1 has already converted free text into the structured query.

Why not RAG with embeddings? Two reasons:

1. **The categories are closed.** A 12-bucket trade taxonomy plus a 50-city geographic taxonomy yields 600 cells. Each cell has at most a few hundred workers. Embedding search adds 30–80ms of latency and zero recall gain over a categorical index over this scale.
2. **The grounding contract is stronger.** With structured retrieval, the verifier can re-derive what should have been retrieved from the Pass 1 record alone — there is no embedding-vector to inspect. This makes V2 (worker grounding) a constant-time set check.

A semantic cache (sentence-level embedding lookup against recent successful Pass 2 outputs) is on the roadmap for cost reduction at scale, but it is a *cache*, not a retrieval primary.

---

## 7. Pricing

The pricing module is a hand-curated rule table maintained as a TypeScript service (`priorityService.ts`). Structure:

```typescript
const Pricing: Record<Trade, Record<City, PriceBand>> = {
  plumbing: {
    casablanca: { low: 200, mid: 450, high: 1200, urgent_premium: 1.4 },
    rabat:      { low: 180, mid: 400, high: 1100, urgent_premium: 1.4 },
    marrakech:  { low: 220, mid: 500, high: 1300, urgent_premium: 1.5 },
    // ... 12 cities
  },
  electrical: { /* ... */ },
  // ... 12 trades
}
```

The bands were initialized from a 200-worker survey conducted in October 2025 and are revised quarterly. The verifier (V4) accepts a generated `price_band_mad` if its midpoint falls within `Pricing[trade][city]` ± 20% (the fairness margin).

This is the part of the system that most directly resists generic chat behavior. A frontier LLM, asked "what does it cost to install a water heater in Salé," will produce a number that sounds plausible to a global audience. The verifier rejects anything that a Moroccan reader would find absurd.

---

## 8. Multimodal

The image branch is decoupled from the chat hot path. When an image is attached to a query:

1. Image → Grok-2-Vision with a classification prompt: "Identify the trade or appliance shown. Return JSON: `{trade: enum | null, confidence: 0..1, note: string}`."
2. The result is injected into the Pass 1 record's `image_evidence` field. The Pass 1 model can use it to override or confirm the textual trade signal.
3. The image bytes are never put into Pass 2's context window.

This costs approximately $0.005 per image classification (Grok-2-Vision). At our current ratio of image-bearing queries (~12%), the multimodal cost is bounded.

A client-side classifier (MobileNetV3 in TensorFlow.js, browser-resident, ~250ms on a mid-tier Android device) is in the roadmap to push image classification to the browser, eliminating the per-image API cost at the trade-off of an offline-trained model. The classifier needs ~50–100 labeled images per trade across 12 trades.

---

## 9. Evaluation

The eval suite is described in [jak-ma-eval-suite/docs/methodology.md](https://github.com/selakkad2003/jak-ma-eval-suite/blob/main/docs/methodology.md). Five dimensions, each scored 0–4 by calibrated raters against a 100-query Darija test set:

- **Factuality** — Does the response correctly reflect the retrieved workers?
- **Naturalness** — Is the Darija idiomatic? Would a Moroccan reader find it natural?
- **Trade-fit** — Does the suggested trade match the implicit user need?
- **Price-fairness** — Is the price band within the local fairness range?
- **Geographic** — Are the recommended workers actually reachable for this user?

Calibration: rater training uses a 20-query anchor set with reference scores. Inter-rater Krippendorff's α target is 0.7. The protocol mirrors the methodology applied in the Baidu ERNIE Mentor Program (October–December 2025) and is documented in [ernie-evaluation-notes](https://github.com/selakkad2003/ernie-evaluation-notes).

Production calibration: we run the eval-suite weekly against a stratified sample of production queries (PII-scrubbed). When aggregate score drops below 3.5 on any dimension, we cut a release-gate ticket.

---

## 10. Production results

Numbers below are from the 60-day window ending 2026-05-01.

| Metric | Value |
|---|---|
| p50 end-to-end latency | 1.18s |
| p99 end-to-end latency | 2.82s |
| Pass 1 + Pass 2 cost per query | $0.0008 |
| Vision cost per image-query | $0.005 |
| Verifier rejection rate | 0.7% |
| Verifier rejection → fallback success | 96% |
| Daily queries (60-day mean) | ~3,400 |
| Daily unique users (60-day mean) | ~1,100 |
| 5-dim eval score (last weekly run) | 3.7 / 4.0 average |

Cost amortization: at 100,000 daily queries (the year-end target), total daily inference cost is approximately $80, dominated by the constrained-generation pass.

---

## 11. Discussion

### Why deterministic verification beats LLM-as-judge for this domain

LLM-as-judge is attractive because it scales without rewriting Python. In a market with no standardized truth, it is also exactly wrong: the judge has the same priors as the generator. If Grok's prior over plumber prices in Salé is biased high, both Grok-the-generator and Grok-the-judge will agree on a biased answer. Deterministic verification — with a rule table that was built by a human survey — breaks the symmetry.

This is the same lesson from constraint-checked code generation: the value of the checker is not that it's perfect, but that it disagrees with the generator on a different axis.

### Why two passes instead of one

A single LLM call could, in principle, do classification + retrieval + generation in one shot via tool use. We did try this. Two failure modes appeared:

1. **Latency tail explodes.** Tool-use models retry frequently when the tool schema is complex; p99 went from 2.8s (current) to 6.4s (single-pass).
2. **The verifier loses its anchor.** With a single output blob, distinguishing "this is the classification step's answer" from "this is the generation step's answer" requires more rules. The current architecture lets V1 check the Pass 1 record, V2-V6 check Pass 2 — clean separation.

### Why not fine-tune

We will. A LoRA fine-tune on Llama 3.1 8B for Pass 2 (constrained generation) is the next compute investment. Rough math: 6 hours on a single A100 (~$20–50 on Modal), targeting ~3× cost reduction at production scale. The fine-tune dataset is the 2,200 PII-scrubbed production samples already collected; target dataset size is 5,000–15,000 by end of 2026.

For Pass 1 (classification), the schema is small enough that the frontier model is fine. Fine-tuning here gives marginal accuracy gains at the cost of additional eval debt.

### What the verifier doesn't catch

The verifier is good at catching *structural* mistakes (worker grounding, city, price band, schema). It is bad at catching:

- **Tone mismatches.** A response that is grammatically correct but emotionally wrong for an urgent water-leak query.
- **Implicit trade misclassification.** If Pass 1 misclassifies "I need someone for my AC" as plumbing instead of HVAC, Pass 2 is generated against the wrong category and the verifier (which only checks within the chosen category) is silent.
- **Long-tail vocabulary.** A worker description that uses a rare French loanword for a tool might trigger V5 (script purity) incorrectly.

These are addressed by the eval suite and by ongoing calibration, not by the verifier.

---

## 12. Roadmap

In rough priority order:

1. **LoRA fine-tune on Llama 3.1 8B for Pass 2.** Target ~3× cost reduction.
2. **Semantic cache** (sentence-level embedding lookup against recent successful Pass 2 outputs). Cost reduction ~2× on top of LoRA.
3. **Browser-side image classifier** (MobileNetV3 + TensorFlow.js). Eliminates per-image API cost.
4. **District federation** — sync localStorage user state across devices for the same logged-in user without serializing to a vendor backend. E2EE blob exchange design, not yet built.
5. **Two more cities** — Tangier and Agadir bring catalog coverage from 12 to 14 metros.
6. **Worker-side scheduling primitive** — current product is match-only. Scheduling is the next product surface.

---

## 13. References & companion repos

- **[jak-ma-eval-suite](https://github.com/selakkad2003/jak-ma-eval-suite)** — Verifier spec, prompts, sample queries, eval runner, methodology docs, latency budget, cost model.
- **[jak-ma-case-study](https://github.com/selakkad2003/jak-ma-case-study)** — Production narrative: decisions, tradeoffs, what broke.
- **[pm-frameworks-darija](https://github.com/selakkad2003/pm-frameworks-darija)** — Pricing taxonomy, evaluation rubric, calibration protocol, verifier philosophy — reusable across Darija NLP projects.
- **[ernie-evaluation-notes](https://github.com/selakkad2003/ernie-evaluation-notes)** — Evaluation methodology from the Baidu ERNIE Mentor Program, where the rater-calibration protocol used here was first applied.
- **[darija-nlp-resources](https://github.com/selakkad2003/darija-nlp-resources)** — Public corpora, papers, and tools for Moroccan-Arabic NLP.

---

## 14. Acknowledgments

This system was built and shipped over the course of the 2025 Tsinghua SIGS AI MSc program. Thanks to early users in Casablanca and Rabat who tolerated bad responses and reported them, and to the Baidu ERNIE Mentor Program (October–December 2025) where the evaluation methodology was sharpened.

---

*This document is the system-level reference for jak.ma as of May 2026. For implementation-level details, see the linked repositories. For questions: sam25@mails.tsinghua.edu.cn.*
