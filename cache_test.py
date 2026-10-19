"""Problem 4: run the agent on all 12 practice docs with and without prompt caching.

Every model call is saved to output/cache_test.json with its setup, document, the token counts the API
reported, and its cost from data/prices.json. The script also checks that each setup did what it claims:
the no_cache setup must show zero cached tokens on every call.

Usage:
    python cache_test.py
"""

import json
import uuid
from collections import defaultdict

from pydantic_ai.messages import ModelResponse

import agent
from tools import DATA_DIR, OUTPUT_DIR, now_iso

PRACTICE_DIR = DATA_DIR / "practice_docs"
KEY_PATH = DATA_DIR / "practice_key.json"
CACHE_TEST_PATH = OUTPUT_DIR / "cache_test.json"
FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision")
MAX_ATTEMPTS = 3


def call_record(setup: str, doc: str, n: int, response: ModelResponse) -> dict:
    """One model call: setup, document, the API's token counts, and its cost from prices.json."""
    cost, breakdown, uncached = agent.cost_usd(response.usage)
    return {
        "setup": setup,
        "doc": doc,
        "call": n,
        "time": response.timestamp.astimezone().isoformat(timespec="seconds"),
        "input_tokens": response.usage.input_tokens,
        "cache_read_tokens": response.usage.cache_read_tokens,
        "cache_write_tokens": response.usage.cache_write_tokens,
        "uncached_input_tokens": uncached,
        "output_tokens": response.usage.output_tokens,
        "reasoning_tokens": response.usage.details.get("reasoning_tokens", 0),
        "cost_usd": round(cost, 8),
        "cost_breakdown_usd": breakdown,
    }


def main() -> None:
    docs = sorted(PRACTICE_DIR.iterdir())
    key = {row["file"]: row for row in json.loads(KEY_PATH.read_text(encoding="utf-8"))}
    # A fresh tag per test so the cache setup starts cold: its first call has to write the cache.
    batch_tag = f"cache-test-{uuid.uuid4().hex[:8]}"
    calls, runs, discarded = [], [], []

    for setup in agent.SETUPS:
        print(f"\n=== setup: {setup} ===")
        for doc in docs:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                result = agent.run(doc, setup=setup, batch_tag=batch_tag, quiet=True, defenses=agent.NO_DEFENSES)
                responses = [m for m in result.messages if isinstance(m, ModelResponse)]
                doc_calls = [call_record(setup, doc.name, n, r) for n, r in enumerate(responses, start=1)]
                # A no_cache run only counts if the API reported zero cached tokens on every call.
                # (A timed-out request that the client retries is sent again byte-for-byte, so the
                # retry can read the cache entry that the first attempt wrote.)
                if setup == "no_cache" and any(c["cache_read_tokens"] for c in doc_calls):
                    discarded.append({"setup": setup, "doc": doc.name, "attempt": attempt,
                                      "reason": "no_cache run reported cached tokens", "calls": doc_calls})
                    print(f"{doc.name:30} attempt {attempt} read the cache -> discarded, rerunning")
                    continue
                break
            else:
                raise SystemExit(f"{doc.name}: no clean no_cache run after {MAX_ATTEMPTS} attempts")
            calls.extend(doc_calls)
            answer = result.answer.model_dump()
            wrong = [f for f in FIELDS if answer[f] != key[doc.name][f]]
            run_cost = sum(c["cost_usd"] for c in doc_calls)
            runs.append({"setup": setup, "doc": doc.name, "calls": len(doc_calls), "cost_usd": round(run_cost, 8),
                         "decision": answer["decision"], "matches_key": not wrong, "wrong_fields": wrong})
            print(f"{doc.name:30} calls={len(doc_calls)} cache_read={[c['cache_read_tokens'] for c in doc_calls]}"
                  f" cost=${run_cost:.6f} {'OK' if not wrong else 'WRONG: ' + ', '.join(wrong)}")

    summary = {}
    for setup in agent.SETUPS:
        mine = [c for c in calls if c["setup"] == setup]
        totals = defaultdict(int)
        for c in mine:
            for field in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "uncached_input_tokens",
                          "output_tokens", "reasoning_tokens"):
                totals[field] += c[field]
        total_cost = sum(c["cost_usd"] for c in mine)
        summary[setup] = {
            "docs": len(docs),
            "calls": len(mine),
            **totals,
            "total_cost_usd": round(total_cost, 8),
            "cost_per_doc_usd": round(total_cost / len(docs), 8),
            "calls_with_cache_reads": sum(1 for c in mine if c["cache_read_tokens"]),
            "discarded_runs": sum(1 for d in discarded if d["setup"] == setup),
        "docs_matching_key": sum(1 for r in runs if r["setup"] == setup and r["matches_key"]),
        }
    summary["percent_saved"] = round(
        100 * (1 - summary["cache"]["total_cost_usd"] / summary["no_cache"]["total_cost_usd"]), 2)
    summary["verified"] = {
        "no_cache_has_zero_cached_tokens": summary["no_cache"]["cache_read_tokens"] == 0,
        # The very first cache-setup call has to write the cache; every call after it should read from it.
        "cache_reads_after_first_call": all(
            c["cache_read_tokens"] > 0 for c in [c for c in calls if c["setup"] == "cache"][1:]
        ),
    }

    CACHE_TEST_PATH.write_text(json.dumps({
        "time": now_iso(),
        "model": agent.MODEL_NAME,
        "prices_per_1m": json.loads(agent.PRICES_PATH.read_text(encoding="utf-8"))[agent.MODEL_NAME],
        "batch_tag": batch_tag,
        "summary": summary,
        "runs": runs,
        "calls": calls,
        "discarded_runs": discarded,
    }, indent=2) + "\n", encoding="utf-8")

    print("\n" + json.dumps(summary, indent=2))
    if not summary["verified"]["no_cache_has_zero_cached_tokens"]:
        print("FAILED: the no_cache setup read tokens from the cache. Those runs don't count.")


if __name__ == "__main__":
    main()
