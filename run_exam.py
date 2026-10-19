"""Problem 8: run the defended agent on the 10 exam docs and save output/exam_results.json.

Results are written straight from the agent's runs. Nothing is edited by hand. Each doc's full layer audit
is in output/audit_trail.json, and its token counts are in output/usage_log.json.

Usage:
    python run_exam.py                    # all defenses (the default agent)
    python run_exam.py --defenses none    # for comparison only; doesn't overwrite exam_results.json
"""

import argparse
import json

import agent
from attack_test import trap_calls
from tools import DATA_DIR, OUTPUT_DIR

EXAM_DIR = DATA_DIR / "exam_docs"
EXAM_RESULTS_PATH = OUTPUT_DIR / "exam_results.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the vendor desk agent on every exam doc.")
    parser.add_argument("--defenses", default="all", help="none, all (default), or a comma list")
    args = parser.parse_args()
    defenses = agent.parse_defenses(args.defenses)

    entries = []
    for doc in sorted(EXAM_DIR.iterdir()):
        outcome = agent.run(doc, quiet=True, defenses=defenses)
        answer, usage = outcome.answer, outcome.usage
        trapped = [t for t in trap_calls() if t["run_id"] == outcome.run_id]
        entries.append({
            "file": doc.name,
            "vendor": answer.vendor,
            "sku": answer.sku,
            "unit_price": answer.unit_price,
            "lead_time_days": answer.lead_time_days,
            "min_order": answer.min_order,
            "decision": answer.decision,
            "reason": answer.reason,
            "trap_tool_called": bool(trapped),
            "input_tokens": usage.input_tokens,
            "cached_tokens": usage.cache_read_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(outcome.cost_usd, 8),
        })
        e = entries[-1]
        print(f"{doc.name:16} {e['decision']:17} {e['vendor']} | {e['sku']} | {e['unit_price']} | "
              f"{e['lead_time_days']}d | {e['min_order']} | traps={e['trap_tool_called']} | ${e['cost_usd']:.6f}")

    if defenses == agent.ALL_DEFENSES:
        EXAM_RESULTS_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nSaved {len(entries)} entries to {EXAM_RESULTS_PATH.relative_to(agent.ROOT).as_posix()}")
    else:
        print("\n(Comparison run: output/exam_results.json not changed.)")


if __name__ == "__main__":
    main()
