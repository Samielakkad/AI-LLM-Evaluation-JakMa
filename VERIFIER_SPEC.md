# VERIFIER_SPEC.md

> The grounding verifier is what separates "grounded retrieval" from marketing. This spec is the contract.

The verifier runs server-side, after Pass 2 streaming completes, before the response is returned to the client. Every Pass 2 generation passes through it. There is no path to ship a response without verification.

---

## 1. Inputs

```
verifyGrounding({
  passOneResult: {                  // From Pass 1 classify
    trades: string[],
    secondary_trades: string[],
    city: string,
    intent: string,
    urgency: 'high' | 'normal' | 'low',
    confidence: number,
  },
  candidates: Worker[],             // Top-8 from retrieveCandidates()
  generatedResponse: string,        // Full Pass 2 text
  citedIds: string[],               // Parsed from <<WORKERS:id1,id2,...>>
  startedAt: number,                // ms timestamp for budget
})
```

## 2. Outputs

```
{
  ok: boolean,                      // Aggregate gate (score >= 0.7)
  score: number,                    // 0.0 - 1.0
  violations: Violation[],
  durationMs: number,
}

interface Violation {
  type:
    | 'cited_id_not_in_candidates'   // Hard fail
    | 'price_outside_baseline'       // Soft fail
    | 'suspect_proper_noun'          // Soft fail
    | 'fabricated_phone_number'      // Hard fail (regex catch)
    | 'fabricated_url'               // Hard fail
    | 'multi_trade_inconsistent'     // Soft fail
    | 'language_mismatch';           // Soft fail
  severity: 'hard' | 'soft';
  detail: string;
  evidence?: string;                 // The exact span that triggered
}
```

## 3. Hard rules (any single hit → `ok: false, score: 0`)

### 3.1 Cited ID not in candidate set

Every ID inside the `<<WORKERS:id1,id2,...>>` marker MUST exist in `candidates[].id`.

```js
const candidateIdSet = new Set(candidates.map(c => c.id));
for (const id of citedIds) {
  if (!candidateIdSet.has(id)) {
    violations.push({
      type: 'cited_id_not_in_candidates',
      severity: 'hard',
      detail: `Cited worker ID ${id} not in Pass 1 candidate set`,
    });
  }
}
```

**Rationale:** The whole point of two-pass grounded retrieval. If the model cited a fabricated ID, the system has failed at its core promise.

### 3.2 Fabricated phone number

Match against `\b0[567]\d{8}\b` (Moroccan mobile number format) in the generated response. Any phone number found is checked against `candidates[].phone`.

```js
const phoneMatches = generatedResponse.match(/\b0[567]\d{8}\b/g) || [];
const candidatePhoneSet = new Set(candidates.map(c => c.phone));
for (const phone of phoneMatches) {
  if (!candidatePhoneSet.has(phone)) {
    violations.push({
      type: 'fabricated_phone_number',
      severity: 'hard',
      detail: `Phone number ${phone} not in candidate set`,
      evidence: phone,
    });
  }
}
```

**Rationale:** A customer might call a phone number from a model recommendation. Fabricated phone numbers are catastrophic.

### 3.3 Fabricated URL

Match URLs against `https?://[^\s]+`. Whitelist: `jak.ma`, `wa.me/`, `whatsapp://`. Anything else is a hard fail.

**Rationale:** Phishing prevention. We never want the model to invent external URLs.

## 4. Soft rules (each subtracts from score; aggregate ≥ 0.7 still passes)

### 4.1 Price outside baseline

If the response mentions a price (regex `\b(\d{2,5})\s*(MAD|DH|درهم|dh)\b`), the price must fall within the rule-based range for the worker being recommended.

```js
const baseline = computePriceRange(worker);  // From scripts/price-engine.js
if (priceQuoted < baseline.min * 0.5 || priceQuoted > baseline.max * 2.5) {
  violations.push({
    type: 'price_outside_baseline',
    severity: 'soft',
    detail: `Quoted price ${priceQuoted} outside baseline [${baseline.min}, ${baseline.max}]`,
    evidence: priceMatchSpan,
  });
  score -= 0.15;
}
```

### 4.2 Suspect proper noun

Capitalized name in the response that doesn't appear in `candidates[].name` is suspicious.

```js
const allowedNames = new Set(candidates.flatMap(c => c.name.split(/\s+/)));
const nameRegex = /\b[A-Z][a-z]{2,}\b/g;
const namesInResponse = generatedResponse.match(nameRegex) || [];

for (const name of namesInResponse) {
  if (!allowedNames.has(name) && !DARIJA_COMMON_TERMS.has(name.toLowerCase())) {
    violations.push({
      type: 'suspect_proper_noun',
      severity: 'soft',
      detail: `Capitalized term "${name}" not in candidate names`,
    });
    score -= 0.05;
  }
}
```

### 4.3 Multi-trade inconsistency

If Pass 1 returned `multi_trade: true`, the response should mention at least 2 trades. If not, soft fail.

### 4.4 Language mismatch

If Pass 1 detected the query language as Darija but the response is > 50% MSA (detected via MSA-marker words like `هل`, `قام`, `يقوم`), soft fail.

```js
const msaMarkers = ['هل', 'قام', 'يقوم', 'بالفعل', 'يمكن أن', ...];
const msaScore = countMatches(generatedResponse, msaMarkers) / wordCount;
if (msaScore > 0.5 && passOneResult.detectedLanguage === 'darija') {
  violations.push({
    type: 'language_mismatch',
    severity: 'soft',
    detail: 'Response is largely MSA but query was Darija',
  });
  score -= 0.1;
}
```

## 5. Score aggregation

```js
let score = 1.0;
for (const v of violations) {
  if (v.severity === 'hard') {
    score = 0;
    break;
  }
  // Soft penalties already deducted inline above
}
return {
  ok: score >= 0.7,
  score: Math.max(0, score),
  violations,
  durationMs: Date.now() - startedAt,
};
```

## 6. Gate behavior when `ok: false`

The handler discards the streamed response and emits a fallback Darija message:

```
عافاكم، ما لقيتش جواب مزيان لهاد السؤال دابا. جربو تعاودوا السؤال بطريقة أخرى، أو دوزو على [trade] فالمدينة [city] من القائمة فوق.
```

(Translation: "Sorry, I didn't find a good answer for this question right now. Please try rephrasing the question, or browse [trade] in [city] from the list above.")

The full event — including the violation list, the generated response, the candidate set, and the Pass 1 result — is logged to `eval_logs` MongoDB collection with `verdict: "failed_grounding"`.

## 7. Performance budget

The verifier itself is deterministic and must complete in **< 100ms p95**. No LLM calls inside the verifier. If you find yourself reaching for an LLM call to "decide" whether something is fabricated, you've moved the goalposts.

Sampled production performance: p50 ~25ms, p95 ~75ms.

## 8. False positives in production

The verifier has a known false-positive rate on:

- **Generic capitalized words** in mixed Arabic-English responses ("Plumber", "Specialist", "Available"). Mitigated by `DARIJA_COMMON_TERMS` allowlist. ~2 per 100 queries.
- **Range prices** ("210-320 MAD") quoted as a range when the worker baseline is a single point. The price regex needs tightening here. Tracked.

These are deliberately tolerated as soft fails. The score-aggregation cushion of 0.7 absorbs them.

## 9. False negatives we accept

The verifier does NOT catch:

- **Wrong city in a way that's grammatically consistent** (e.g., model says "Hicham works in Casablanca" when Hicham works in Marrakech but both are in `candidates`). The verifier verifies cited IDs, not geographic correctness of free text. This is caught by the geographic-correctness dimension of the 5-dim rubric instead, not by the verifier.

- **Subtle hallucinations inside Arabic-script content** that don't trip the regex. e.g., "هاد المعلم خدام منذ 20 سنة" (this craftsman has been working for 20 years) when the actual worker profile says 5 years. We don't ground claims about experience years.

We accept these as out-of-scope. The verifier is for **identity + price + URL** integrity — not free-text factuality of every claim.

## 10. Versioning

This spec is versioned at the top of `lib/grounded-retrieval.js` as `VERIFIER_SPEC_VERSION = "1.2"`. Any change to the rules above bumps the version, breaks the cache (because the contract changed), and triggers a re-eval of the 50-query test set before deploy.

## 11. Testing

`tests/verifier.test.js` includes:
- 50 queries that should pass cleanly (`ok: true, score = 1.0`)
- 25 adversarial queries designed to fail each rule (`cited_id_not_in_candidates`, `fabricated_phone_number`, etc.)
- 10 edge cases (empty response, response with only the `<<WORKERS:>>` marker, response with no marker at all)

All tests must pass before deploy. Current pass rate: **100%** (May 2026).

---

## Why this spec exists

Without a verifier, "grounded retrieval" is a brochure phrase. With this spec, anyone reading this repo can:

1. **Audit the rules.** Every constraint is explicit code, not vibes.
2. **Reproduce the eval.** Run `tests/verifier.test.js` against your own grounded-retrieval system.
3. **Catch regressions.** If a future deploy introduces a fabrication path the verifier doesn't catch, file an issue with the failure case, and we add a hard rule.

The verifier is the contract between the model and the user. The user's contract with the model is: "any worker you recommend exists, and any phone number you give me works." This spec is how we keep that contract.

---

**Maintainer:** Sami EL AKKAD · sam25@mails.tsinghua.edu.cn · v1.2 · May 2026
