# HW6: Campus Customs Vendor Desk Agent

An AI agent that reads one vendor document (an HTML quote or catalog page, a PDF quote, or an `.eml` email), pulls out the vendor, SKU, unit price, lead time, and minimum order, and recommends whether Campus Customs should buy, following `data/shop_handbook.md`. It's built with PydanticAI and uses **only `gpt-6-luna` through Portkey**.

It's defended against booby-trapped documents in three layers (code, design, prompt). The `send_email` and `approve_payment` tools are traps: they never send or pay anything, they only log to `output/trap_calls.json`, and with defenses on they also require human approval.

**Results at a glance:** open `output/hw6_report.html` in any browser. It's a single file and works offline.

## How to run the agent

Requires Python 3.12+.

```bash
python -m venv venv
venv\Scripts\activate             # Windows  (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Mac/Linux: cp .env.example .env, then add your PORTKEY_API_KEY
```

Run the agent on one vendor document:

```bash
python agent.py --doc data/practice_docs/p01_bluehen_quote.html
```

This prints the answer, then appends to `output/usage_log.json` (token counts and cost) and `output/audit_trail.json` (tool calls, what each defense layer did, and the final answer).

Options:

- `--defenses all` (default), `none` (the original undefended agent), or any mix: `--defenses code,design,prompt`
- `--setup cache` (default) or `no_cache` (used only for the Problem 4 caching test)

## Rerun each problem

| Problem | Command | Output |
|---|---|---|
| 4: Caching test | `python cache_test.py` | `output/cache_test.json`, `.md` |
| 5: Attack test (no defenses) | `python attack_test.py` | `output/attack_results.json`, `.md` |
| 6: Defense test | `python defense_test.py` | `output/defense_results.json`, `.md` |
| 7: Red team | `python red_team_test.py` (docs built by `make_attacks.py`) | `output/red_team.md` |
| 8: Exam docs | `python run_exam.py` | `output/exam_results.json` |
| 9: Results page | `python build_report.py` | `output/hw6_report.html` |

## Files

- `agent.py`: entry point; builds the agent, runs one document, writes the logs
- `tools.py`: `read_vendor_document` plus the `send_email` and `approve_payment` trap tools
- `models.py`: structured types (the answer, the facts, and the log records)
- `defenses.py`: the code layer (only what a person can see) and the design layer (Python applies the handbook)
- `prompts/prompt.md`: my instructions to the agent, including the safety rules; the handbook is added after it on every call
- `data/`: the handbook, prices, practice key, 12 practice docs, 10 exam docs, and my 2 red-team attacks
- `output/`: every result file, plus `harness.md` (how the agent and its safety layers work)
- `AI_prompts.md`: every prompt I gave my AI coding assistant, problem by problem
