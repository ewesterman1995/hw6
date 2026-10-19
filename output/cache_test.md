# Cache Test: With vs. Without Cached Tokens

**Problem 4.** I ran the vendor desk agent on all 12 practice docs in two setups and recorded the token counts the API reported on every model call. Raw data: `output/cache_test.json` (48 kept calls plus 6 discarded runs). Script: `python cache_test.py`.

| Setup | How it's configured | What it should show |
|---|---|---|
| **cache** | A cache breakpoint right after the handbook (`openai_cache_instructions=True`). The batch starts cold with a fresh tag, so the first call has to write the cache. | 1 cache write, then cache reads on every later call |
| **no_cache** | Explicit cache mode with no breakpoints (`prompt_cache_options.mode = "explicit"`), plus a unique random id at the very start of **every** request, so no request can ever match a cached prefix. | 0 cached tokens on every call |

Both setups send the same prompt, handbook, tools, and documents. Model: `gpt-6-luna` through Portkey.

---

**Verified from the API's token counts.** The no_cache setup read **0 cached tokens on all 24 calls**. The cache setup read from the cache on **23 of 24** (all but the very first call, which wrote it). Six no-cache runs that touched the cache were thrown out and rerun: a request that timed out was re-sent byte-for-byte, so the re-send could read what the first attempt cached. Those runs are kept under `discarded_runs` in the JSON but left out of every number below.

---

## 1. Total cost and cost per doc

| | cache | no_cache |
|---|---|---|
| Docs | 12 | 12 |
| Model calls | 24 (2 per doc) | 24 (2 per doc) |
| Input tokens | 265,641 | 265,966 |
| Output tokens | 2,293 | 2,221 |
| **Total cost** | **\$0.005546** | **\$0.034281** |
| **Cost per doc** | **\$0.000462** | **\$0.002857** |

$$
\text{Saved} = 1 - \frac{\$0.005546}{\$0.034281} = \boxed{83.8\%}
$$

Caching made each document about **6.2× cheaper** (\$0.002857 ÷ \$0.000462).

### Where the money went

| Cost line | cache | | no_cache | |
|---|---|---|---|---|
| Cache reads (\$0.01/1M) | \$0.002498 | 45.0% | \$0 | 0% |
| Cache writes (\$0.125/1M) | \$0.001599 | 28.8% | \$0.032868 | 95.9% |
| Uncached input (\$0.10/1M) | \$0.000302 | 5.5% | \$0.000302 | 0.9% |
| Output (\$0.50/1M) | \$0.001146 | 20.7% | \$0.001110 | 3.2% |

Of the cache setup's write cost, \$0.001358 is the single first-call write. The other \$0.000241 comes from the small writes on every later call.

---

## 2. Real numbers vs. my Problem 2 estimate

Problem 2 estimated the **handbook alone**: 10,058 tokens, **one call** per document.

### Tokens per call

$$
\underbrace{10{,}058}_{\text{handbook}} + \underbrace{448}_{\text{prompt.md}} + \underbrace{\approx 484}_{\text{tool definitions, output schema, formatting}} \approx \underbrace{10{,}990}_{\text{API: average call-1 input}}
$$

The `tiktoken` handbook count was fine, but the handbook is only about 91.5% of what goes out on every call. The second call of each run averages 11,147 input tokens, because it also carries the document text and the tool call.

### Calls per document

Problem 2 assumed **1 call** per document. The real agent makes **2 calls**: (1) the model decides to call `read_vendor_document`, then (2) it reads the result and returns the answer. **The handbook goes out twice per document.**

### Cost comparison (12 docs)

| | Problem 2 estimate (handbook only, 1 call/doc) | Real (everything, 2 calls/doc) | Real ÷ estimate |
|---|---|---|---|
| Without cache | 12 × \$0.0010058 = **\$0.012070** | **\$0.034281** | **2.84×** |
| With cache | \$0.0012573 + 11 × \$0.0001006 = **\$0.002364** | **\$0.005546** | **2.35×** |
| % saved | 80.4% | 83.8% | |

What explains the gap, per uncached call:

$$
\frac{\$0.001387 \text{ (real no-cache call 1)}}{\$0.0010058 \text{ (estimate)}} \approx 1.38
\;\approx\;
\underbrace{\tfrac{10{,}990}{10{,}058}}_{\text{1.09: more tokens}} \times \underbrace{\tfrac{\$0.125}{\$0.10}}_{\text{1.25: billed as cache writes}}
$$

Then × 2 calls per doc, plus output tokens, gives about 2.8×.

**The % saved held up.** The estimate said caching saves about 80–90%; the real number is 83.8%. If the no-cache calls had been billed at the plain \$0.10 input rate instead of as cache writes, the real saving would have been **80.0%**.

---

## 3. Projection: 1,000 docs/day for 30 days (30,000 docs)

$$
\text{Monthly cost} = \text{cost per doc} \times 30{,}000
$$

| | Per doc | **30 days** |
|---|---|---|
| **Without cache** | \$0.002857 | **\$85.70** |
| **With cache** (simple: my measured per-doc average) | \$0.000462 | **\$13.86** |
| **With cache** (steady state: see note) | \$0.000357 | **\$10.76** |

$$
\$85.70 - \$13.86 = \$71.84 \text{ saved per month } (83.8\%)
\qquad \text{steady state: } \$85.70 - \$10.76 = \$74.94 \;(87.4\%)
$$

**Steady-state note.** My 12-doc test includes one full cache write (the first doc, \$0.001619). At 1,000 docs a day the cache stays warm, since it lasts at least 30 minutes, so that write happens rarely. Steady state uses the average of docs 2–12 (\$0.000357), plus one fresh cache write per day:

$$
30{,}000 \times \$0.000357 + 30 \times \$0.001619 = \$10.71 + \$0.05 = \$10.76
$$

For comparison, Problem 2's handbook-only math for 30,000 calls gave \$30.17 without cache and \$3.02 with cache. The real monthly bill is higher in both setups, for the reasons in section 2.

---

## 4. Reflection: what surprised me

### Surprise 1: two model calls per document

I expected one call per document. The agent makes two: call 1 decides to read the document, and call 2 reads it and answers. The model keeps no memory between calls, so **the whole handbook goes out twice**.

| | Call 1: "decide to read the doc" | Call 2: "read it and answer" |
|---|---|---|
| Input tokens (avg) | 10,990 | 11,145 |
| Output tokens (avg) | **29** (just `read_vendor_document(path)`) | 160 (the answer) |
| Cost with cache (avg) | \$0.000138 (**39%** of the doc) | \$0.000219 |
| Cost without cache (avg) | \$0.001387 (**49%** of the doc) | \$0.001470 |

Call 1 sends about 11,000 tokens to get back 29. Without cache, it accounts for about **\$42 of the \$85.70** monthly projection. With cache, it's about \$4.

**Why it happens:** I told the agent to read the document with a tool, so it has to ask for the document before it can see it. **What I could change:** if `agent.py` read the file and put the text straight into the first message, each document would need one call. The tradeoff is that the audit trail would no longer show a separate "read" step.

### Surprise 2: my tools cost more tokens than I expected

Every call sends the full description of every tool, used or not. My share estimates (measured with `tiktoken` on the tool definitions, then scaled to the API's total):

| Tool definition | Share | ≈ Tokens per call |
|---|---|---|
| `final_result` (the answer format: all 7 `VendorDecision` fields with descriptions) | 51% | ~235 |
| `approve_payment` (trap) | 18% | ~80 |
| `send_email` (trap) | 16% | ~75 |
| `read_vendor_document` | 16% | ~70 |
| **Total** | | **~460** |

- The biggest piece isn't a tool I wrote. PydanticAI turns my `VendorDecision` output type into a hidden `final_result` tool, so the field descriptions in `models.py` are paid for on every call.
- My two trap tools never run, but they add about **155 tokens to every call**. That's the price of having the trap set.
- Add `prompt.md` (448 tokens) and I'm sending about **930 tokens** on top of the 10,058-token handbook, on every call.

### Surprise 3: no cache costs *more* than the regular input price

I assumed "no cache" meant the normal \$0.10/1M input rate. There are actually three input prices:

| What happens to input tokens | Rate per 1M |
|---|---|
| Plain input (processed, not saved) | \$0.10 |
| **Cache write** (processed *and* saved for reuse) | **\$0.125** |
| Cache read (reused from the save) | \$0.01 |

- **Why a write costs more:** the provider does the normal work and then stores the result in memory so a later call can skip that work. The 25% premium pays for the storage, and it earns itself back on the first reuse.
- **The catch:** for any prompt over about 1,000 tokens, this API reports every new input token as a cache write, even in explicit "don't cache" mode where nothing is ever reused. I sent the identical request twice in that mode: both reported about 10,087 tokens written, and the second read 0.
- **The cost:** 262,942 written tokens × the extra \$0.025/1M = **\$0.0066**, which is **19% of my no-cache bill**. At the plain \$0.10 rate, no-cache would have cost \$0.0277 instead of \$0.0343, and caching would have saved 80.0% instead of 83.8%.

**Takeaway:** with a prompt this size on this API, the first send pays the write price no matter what. Skipping the cache means paying that premium on every call and getting nothing back. Turning caching on is close to free money.

---

## 5. Side note: accuracy

Both setups got the **same 8 of 12** documents right against `practice_key.json`. Caching changed the bill, not the answers. The four misses were the same in both setups:

| Doc | Wrong fields |
|---|---|
| p02 | unit_price, decision |
| p03 | vendor, decision |
| p07 | lead_time_days, decision |
| p12 | unit_price, decision |

No trap tools were called (`trap_calls.json` is still `[]`).
