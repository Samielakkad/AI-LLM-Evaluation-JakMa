# Latency Budget — How We Set p50 < 6s and Hit It

> Budgets are claims about the world. This doc shows how we set the jak.ma latency budget, what it actually measures in production, and what the trade-offs look like.

---

## 1. Why a budget at all

LLM latency in 2026 is a chain of independently-tunable components. If you don't budget per component, you'll spend 80% of your engineering time speeding up the cheapest component while the bottleneck sits unattended.

We picked our p50 (6s) and p95 (15s) budgets based on three things:

1. **Mobile network reality in Morocco.** Median mobile latency on 4G in Casablanca is ~120ms RTT. On 3G in smaller cities (which is still common in 2026): ~400ms RTT. Your TTFB needs to be under 2s OR users assume the page is broken.

2. **WhatsApp comparison.** Users transition from in-chat AI conversation to WhatsApp contact. WhatsApp message round-trips are ~1–2s. Our in-app AI conversation should feel comparable, not slower.

3. **Mobile device CPU constraints.** Even if our server is fast, the client device has to render Arabic-script text + worker cards. Median Moroccan device in 2026 is a mid-tier Android with 4GB RAM and a 2022-era chipset. Heavy DOM rebuilds during streaming are visibly janky.

These three constraints land you at a "p50 < 6s, p95 < 15s" budget for end-to-end chat response (from user pressing send to full response visible).

---

## 2. The component budget

| Component | Budget | Live p50 (May 2026) | Live p95 | Notes |
|---|---|---|---|---|
| HTTP + JSON parse | 100ms | ~30ms | 80ms | Vercel edge → MongoDB Atlas region |
| BM25 pre-filter (in-memory) | 30ms | ~8ms | 20ms | Skip Pass 1 in ~40% of queries |
| **Pass 1 — Grok-3-mini classify** | **4s** | **~800ms** | **2.4s** | xAI API roundtrip, JSON mode |
| Retrieval — MongoDB query | 200ms | ~40ms | 180ms | Composite index on `(category, city, approved, available)` |
| Semantic cache check | 50ms | ~10ms | 25ms | Mongo lookup on canonical query hash |
| **Pass 2 — Grok-3-mini TTFT** | **2s** | **~1.1s** | **3.0s** | First-token latency from xAI streaming |
| **Pass 2 — Grok-3-mini full stream** | **8s** | **~3.2s** | **7.8s** | ~600 tokens at ~200 tok/s |
| Verifier (deterministic) | 100ms | ~25ms | 75ms | No LLM call, pure code |
| eval_logs persistence | 100ms | ~20ms | 60ms | Async, doesn't block response |
| Client render | 200ms | ~80ms | 250ms | Re-render of worker cards alongside text |
| **End-to-end p50/p95** | **6s / 15s** | **~4.5s** | **~12s** |

The budgets sum to more than the totals because some components run in parallel (e.g., BM25 pre-filter and Pass 1 race; whichever finishes first picks the path).

---

## 3. Where the time actually goes

In production sampling (n=10k recent queries, May 2026):

```
% of total time spent in each component (p50)
┌──────────────────────────────────────────┐
│ Pass 1 (Grok classify)         18%       │
│ BM25 pre-filter                <1%       │
│ Retrieval (Mongo)               1%       │
│ Cache check                     <1%      │
│ Pass 2 TTFT (model warmup)     24%       │
│ Pass 2 streaming (rest)        53%       │
│ Verifier                        1%       │
│ Client render                   2%       │
│ Other (HTTP, JSON, etc.)        1%       │
└──────────────────────────────────────────┘
```

**Pass 2 streaming (53%) is the dominant cost.** This is the model generating the response text. We don't control xAI's token-rate, so this is mostly a "wait" cost.

**Pass 1 classification (18%)** is the second largest. We could cut this with a fine-tuned classifier (~150ms inference vs. ~800ms API call) — see `methodology.md` §9 for the trade-off discussion.

---

## 4. How we got from "20s p50 demo" to "4.5s p50 production"

Iteration history (the wins, in order):

### v0 (Mar 2026) — naive single-pass, p50 = 19.2s
- One Grok call per query, free generation, no streaming.
- Why it was slow: ~12s waiting for full response before user saw anything.

### v1 (Apr 2026) — Streaming, p50 = 8.4s
- Added SSE streaming. User sees first tokens in ~2s instead of 12s.
- p50 improved more than p95 because streaming reduces perceived-latency more than total-time.

### v2 (Apr 2026) — Two-pass + retrieval, p50 = 7.1s
- Added Pass 1 classify + Mongo retrieve. Total wall-clock slightly increased, BUT we now had ID-citation enabled.

### v3 (May 2026, post-Claude-Code-deploy) — BM25 + semantic cache, p50 = 4.5s
- BM25 pre-filter short-circuits 40% of Pass 1 calls.
- Semantic cache returns ~22% of Pass 2 responses without ANY model call.
- This is where most of the gain came from. Result: 1.4× speedup on cached path, 2.1× speedup on uncached path.

### What we tried that didn't work

- **Smaller Grok variant (Grok-3-mini-nano, hypothetical)** — quality dropped below verifier-pass threshold. Reverted.
- **Aggressive parallel Pass 1 + retrieval** — racing them adds complexity but only saved 60ms p50. Not worth the eval complexity.
- **Caching the full Pass 1 result for repeat queries** — partially worked, but cache invalidation on worker-pool changes was tricky. We cache the Pass 2 response instead (TTL 6h, invalidates on worker status changes).

---

## 5. What we don't measure (yet)

Honest list of gaps:

- **Time-to-relevant-token**: when does the FIRST useful word appear? Today we measure TTFT (any token). For Pass 2 responses, the first 30 tokens are often boilerplate ("Hi! For your request in...") before the model gets to the worker recommendation.
- **Render-blocking time**: when does the worker card appear visually? We log when the SSE marker is parsed, but not when the React state update completes the DOM mutation.
- **Network-jitter robustness**: our p50/p95 numbers are from production traffic, which biases toward users with good connections. Real-world tail might be worse for poor-connection users.

Tracked as work-in-progress.

---

## 6. Headroom — how much budget remains before users churn

We have data on session-completion rate vs. response latency:

```
Latency bucket   | Session completion %
─────────────────┼─────────────────────
< 3s             | 84%
3-5s             | 78%
5-8s             | 71%
8-12s            | 58%
12-20s           | 33%
> 20s            | 9%
```

(Defined: user receives response AND clicks WhatsApp contact within same session.)

At our current p50 of 4.5s, we're in the 78% bucket. Pushing p50 to 3s would gain ~6 percentage points of session completion. That's the business case for further latency work, not "speed is good in general."

---

## 7. Run-this-yourself

To measure your own grounded-retrieval endpoint's latency profile:

```bash
python scripts/run_eval.py \
    --endpoint https://your-domain.com/api/ai/chat \
    --test-set data/sample_queries.jsonl \
    --output your-results.json

# Read latency block:
cat your-results.json | jq '.latency'
```

The output JSON has `latency.p50_ms`, `latency.p95_ms`, `latency.mean_ms`.

For a granular breakdown matching the table in §2, expose per-component timing in your endpoint as response headers (e.g., `Server-Timing`).

---

**Sami EL AKKAD** · Tsinghua SIGS AI MSc · sam25@mails.tsinghua.edu.cn
