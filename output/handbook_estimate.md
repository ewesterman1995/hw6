# Handbook Cost Estimate

**Problem 2: Size up the handbook.** `data/shop_handbook.md` is sent to `gpt-6-luna` on **every** call, so its size sets a minimum cost for each document the vendor desk agent processes.

---

## 1. Token count

$$
\boxed{T_{\text{handbook}} = 10{,}058 \text{ tokens}}
$$

### How I got it

I ran the handbook through OpenAI's `tiktoken` library (v0.14.0) in the project `venv`:

```python
import tiktoken
text = open("data/shop_handbook.md", encoding="utf-8").read()
len(tiktoken.get_encoding("o200k_base").encode(text))   # -> 10058
```

| Measure | Value |
|---|---|
| Characters | 28,903 |
| Words | 6,127 |
| Lines | 338 |
| **Tokens (`o200k_base`)** | **10,058** |
| Tokens (`cl100k_base`, older encoding, for comparison) | 10,184 |

- **Why `o200k_base`:** this is the encoding used by OpenAI's current GPT models. `tiktoken` has no entry for `gpt-6-luna` by name (`encoding_for_model("gpt-6-luna")` raises an error), so I chose the current-generation encoding myself.
- **Sanity check:** $28{,}903 \text{ chars} \div 10{,}058 \text{ tokens} \approx 2.9$ characters per token. Plain English usually runs about 4 characters per token. This handbook comes out lower because the 180-row product catalogue (section 9) is full of SKUs, dollar amounts, and `|` table pipes, which split into many small tokens.
- **Caveat:** the real API bill will be a little higher. The handbook gets wrapped in a chat message, which adds a few formatting tokens, and it sits next to our instructions and the vendor document. Problem 4 will compare this count with the `usage` numbers the API actually reports.

---

## 2. Prices (`data/prices.json`)

| `gpt-6-luna` rate | Price per 1M tokens | Price per token |
|---|---|---|
| Input (uncached) | \$0.10 | \$0.0000001 |
| Cached input (cache hit) | \$0.01 | \$0.00000001 |
| Cache write (first time a prefix is cached) | \$0.125 | \$0.000000125 |
| Output | \$0.50 | \$0.0000005 |

The handbook is **input**, so output pricing doesn't apply to this estimate.

---

## 3. Cost of the handbook alone

General formula:

$$
\text{Cost} = T_{\text{handbook}} \times \frac{\text{rate per 1M}}{1{,}000{,}000}
$$

### A. Without caching (every call pays the full input price)

**One call:**

$$
C_{\text{uncached}}^{(1)} = 10{,}058 \times \frac{\$0.10}{1{,}000{,}000} = \$0.0010058 \approx \$0.0010
$$

**1,000 calls:**

$$
C_{\text{uncached}}^{(1000)} = 1{,}000 \times \$0.0010058 = \boxed{\$1.0058 \approx \$1.01}
$$

### B. With caching

With caching, the first call **writes** the handbook into the cache at the cache-write rate. Every later call that starts with the exact same handbook text **reads** it at the much cheaper cached rate.

**Cost of one cache write (first call):**

$$
C_{\text{write}} = 10{,}058 \times \frac{\$0.125}{1{,}000{,}000} = \$0.00125725 \approx \$0.0013
$$

**Cost of one cache hit (every later call):**

$$
C_{\text{hit}} = 10{,}058 \times \frac{\$0.01}{1{,}000{,}000} = \$0.00010058 \approx \$0.0001
$$

**One call.** On its own, a single call is always the first call, so it pays for the write:

$$
C_{\text{cached}}^{(1)} = C_{\text{write}} = \$0.00125725
$$

That's about 25% *more* than the uncached call. With only one call, caching costs extra.

**1,000 calls (1 write + 999 hits):**

$$
\begin{aligned}
C_{\text{cached}}^{(1000)} &= C_{\text{write}} + 999 \times C_{\text{hit}} \\
&= \$0.00125725 + 999 \times \$0.00010058 \\
&= \$0.00125725 + \$0.10047942 \\
&= \boxed{\$0.10173667 \approx \$0.10}
\end{aligned}
$$

### C. Savings at 1,000 calls

$$
\text{Savings} = \$1.0058 - \$0.1017 = \$0.9041
\qquad
\frac{\$0.9041}{\$1.0058} \approx \boxed{89.9\%\ \text{cheaper}}
$$

**Break-even.** Caching pays for itself starting with the second call:

$$
\underbrace{\$0.00125725 + \$0.00010058}_{\text{cached, 2 calls}} = \$0.00135783
\;<\;
\underbrace{2 \times \$0.0010058}_{\text{uncached, 2 calls}} = \$0.0020116
$$

---

## 4. Summary

| Scenario | 1 call | 1,000 calls |
|---|---|---|
| **No caching** | \$0.0010058 | **\$1.0058** |
| **With caching** (1 write, then hits) | \$0.0012573 | **\$0.1017** |
| Cached, best case (every call a hit) | \$0.0001006 | \$0.1006 |

## 5. Assumptions to test in Problem 4

1. **Tokenizer:** `gpt-6-luna` counts tokens the same way as `o200k_base`.
2. **Cache hits:** the handbook goes **first** in the prompt and stays byte-for-byte identical on every call. Caching only reuses an identical prefix, so a single changed character before or inside the handbook means a miss and full price.
3. **Cache lifetime:** the cache stays warm between calls. If it expires (for example, during a long pause between documents), the agent pays for another write.
4. **Scope:** these numbers cover the handbook only. Instructions, the vendor document, tool definitions, and output tokens all come on top.
