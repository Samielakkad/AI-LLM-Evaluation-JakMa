# Methodology — Why Two-Pass Grounded Retrieval + Verifier

> This doc is the long-form answer to "why this architecture and not something simpler / something fancier."

The eval suite in this repo evaluates a specific architecture: classification, then retrieval, then constrained generation, then verification. There are simpler architectures (vanilla RAG, fine-tuned single-pass) and fancier architectures (multi-agent, tool-use, chain-of-verification). This doc explains why jak.ma settled where it did.

---

## 1. The failure mode that drove every architectural decision

jak.ma is a **marketplace**. Users contact workers via WhatsApp. Phone numbers are first-class data.

If the AI invents a phone number, a customer might call it. The fact that the model "hallucinated rarely" or "passed 92% of evals" is not the framing — the framing is **catastrophe per failure**, not average performance. One fake phone number that connects to a stranger destroys the trust contract for an unknown radius of users around the failure event.

This pushes us toward an architecture where **fabrication is structurally impossible**, not just statistically rare. That's a strong constraint. Most LLM architectures are statistical-rarity architectures.

The verifier is the structural lock. The two-pass classify-then-generate-constrained pattern is what makes the verifier tractable (we know what set of IDs are legal because Pass 1 told us).

---

## 2. Why not just vanilla RAG?

**Vanilla RAG:** retrieve top-k docs → stuff them into the prompt → let the model generate freely.

What goes wrong in jak.ma:

1. The model can ignore retrieved docs and pull from training-data priors. "Plumbers in Casablanca" is a common-enough concept that the model can confabulate a "Mohammed Bennani" or a "+212 6XX XXX XXX" without consulting the retrieved candidates.
2. The model can mix retrieved info with hallucinations. It can correctly cite Yusuf-the-plumber's existence but invent his phone number.
3. There's no clean structural way to verify the output without re-running the retrieval step yourself.

The two-pass + ID-citation marker approach forces the model to **commit** to specific candidates, which the verifier can then check exhaustively.

---

## 3. Why not a fine-tuned single-pass model?

We're scaffolding a Darija LoRA fine-tune for v4 (see `scripts/finetune/`), but it's not the production path today. Three reasons.

### 3.1 Iteration speed

A fine-tuned model is brittle to behavior changes. The "show worker cards alongside streamed text" feature lives in Pass 2's marker emission. To change the marker format, you re-fine-tune. With a prompt-engineered Grok-3-mini, you change a prompt and ship.

### 3.2 Verification still required

A fine-tuned model can still hallucinate worker names. Fine-tuning reduces failure rate but doesn't eliminate it. We'd still need the verifier. The fine-tune isn't replacing the architecture — it's potentially a cost-and-quality improvement on Pass 2 generation.

### 3.3 Dataset bootstrap problem

To fine-tune well on jak.ma's task, we need ~5–15k high-quality Darija conversation pairs with correct grounding behavior. Producing that dataset is itself a few months of work (see `darija-nlp-resources` repo for the corpora gap). The current Grok-3-mini path is the lower-friction starting point that gets a deployable system in week 1, not week 16.

---

## 4. Why two passes and not chain-of-thought / chain-of-verification?

Multi-step prompting patterns like chain-of-thought (CoT), chain-of-verification (CoV), and ReAct work well when:

- The output requires symbolic reasoning the model finds hard zero-shot
- The reasoning trace is the value (the user wants to see why)
- Latency budget is generous

jak.ma's Pass 2 is **fluent classification-conditioned generation**. The hard work is selecting which worker to recommend (Pass 1 already framed it) and writing a Darija paragraph (which the model is already good at). CoT/CoV would add latency without value.

The "thinking pane" UI feature (showing Pass 1's parsed output to the user) gives users the reasoning-trace benefit without paying for it inside Pass 2. Best of both.

---

## 5. Why MongoDB and not a vector database?

The retrieval step in Pass 2 is **structured filtering**, not semantic similarity. The query is "plumbers in Tangier sorted by rating, take top 8." That's a SQL/Mongo filter, not a vector lookup. Adding a vector database would add latency (~50–150ms) for no functionality gain.

Where vectors WOULD help:
- Semantic similarity on description text (e.g., "find workers who mention 24/7 emergency in their bio") — but BM25 keyword matching covers this at 5% the cost.
- Cross-trade routing — but we route via Pass 1's classifier output, which is more interpretable.

We add a BM25 keyword pre-filter (see `cost_model.md`) which gives most of the vector-similarity benefit for queries that have natural-language overlap with the worker descriptions. Production cache hit rate: ~22% of queries skip Pass 1 entirely.

---

## 6. The cost geometry that locked in the architecture

Production constraints:
- Total infra budget: <200 MAD/month (~$20)
- 0% commission (no revenue per transaction)
- ~5,000 chat queries/month current volume; need to scale to ~50,000 without going over budget

With those constraints, the architecture had to satisfy:
- ≤$0.05 per query at scale (the budget allows ~$10/month for AI cost at 50k queries)
- ≤6s p50 latency (mobile users on uneven connections drop off if longer)
- Production-monitorable (eval logs, latency dashboards, failure replay)

The chosen architecture lands at ~$0.043 per query effective (after BM25 + semantic cache) and ~4.5s p50 latency. See `cost_model.md` for the breakdown.

---

## 7. What we'd change with more compute / dataset budget

If we had 10× the compute budget and 20× the labeled Darija data:

- **Replace Pass 1 with a fine-tuned Darija classifier** trained on production logs. Faster, cheaper, more accurate on edge cases.
- **Train an on-device tiny LLM** (1–3B params, INT4) for Pass 2 on common queries. The cache layer already shows that 22% of queries are essentially repeats — those don't need a frontier API call.
- **Replace BM25 with a proper hybrid (BM25 + ColBERT or BGE-M3)** for the long tail of queries where keyword match misses.
- **Add an interventional verifier**: today's verifier flags violations; an interventional one could re-prompt the model on detected fabrications. Higher cost, but reduces fallback message frequency.

None of these are blockers. The current architecture is **production-correct at our budget**.

---

## 8. What we explicitly chose NOT to do

- **No agentic / multi-tool patterns.** The architecture should be a function call, not a planning loop. Loops are expensive to monitor and even more expensive to evaluate.

- **No "let the model decide what to do."** Every routing decision is in code: Pass 1 schema is structured, retrieval is a Mongo query, Pass 2 is constrained generation. The model is a constrained component, not a god-mode controller.

- **No auto-routing between models.** The architecture uses Grok-3-mini for everything. We considered a routing layer (cheap model for easy queries, expensive model for hard queries), but the cost win didn't justify the eval complexity (you now have to score TWO models against the rubric, and you have to test the router).

- **No streaming the cited IDs separately.** We considered a SSE event for `candidates` separate from the text stream. Single-stream with end-of-text marker is operationally simpler and matches the frontend's expectations (workerCards re-render once the marker is parsed).

---

## 9. What I'd want a Microsoft / MSRA reviewer to push back on

Genuine open questions in this architecture:

1. **Pass 1 classifier latency.** ~800ms p50 is most of the user-visible response time gap before token streaming begins. If we replaced Grok-3-mini-JSON-mode with a smaller fine-tuned classifier, we could get p50 below 200ms — but at what eval-cost? This is a real trade-off.

2. **Verifier false-positive cost.** ~2 false positives per 100 queries get gated to fallback. That's 2 failed user experiences. Is the 0% fabrication rate worth the 2% over-cautious-rejection rate? In our domain (calling-a-phone-number-stakes), yes. In a domain where the cost-of-a-bad-recommendation is lower, maybe not.

3. **Cache poisoning.** Semantic cache returns prior responses. If a worker leaves the platform and a cached response still recommends them, the next 6 hours of cache hits will give stale data. Mitigation: cache invalidates on worker status changes. But this is a real consistency cost.

4. **Geographic-correctness drift.** Pass 1 maps non-canonical cities to canonical ones (`بني ملال` → fallback to nearest canonical). Over time, demand from non-canonical cities accumulates, and the platform should add them. The eval-suite doesn't currently track this drift.

I welcome conversations on any of these. Email: sam25@mails.tsinghua.edu.cn.

---

## 10. Citations

The architectural patterns above are not novel in isolation:

- Two-pass classify-then-generate: Standard pattern in production LLM deployments. Anthropic's [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) (2024) makes the case clearly.
- Verifier-gated generation: see "Self-Refine" (Madaan et al., 2023), "Chain of Verification" (Dhuliawala et al., 2023).
- BM25 + dense hybrid retrieval: well-established. See "BEIR" benchmark (Thakur et al., 2021) for evaluation methodology.
- Semantic caching for LLM cost: GPTCache (Bang, 2023) provides one open-source instantiation.

What's specific to jak.ma is the **integration into a production marketplace with verifier-as-structural-lock for identity-and-phone-number integrity**. That part isn't in the literature yet (as of May 2026), which is why this repo exists.

---

**Sami EL AKKAD** · Tsinghua SIGS AI MSc · sam25@mails.tsinghua.edu.cn
