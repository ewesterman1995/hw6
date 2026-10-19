"""Campus Customs vendor desk agent: runs on one vendor document and logs answer, tools, and cost.

Usage:
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html                  # all defenses (default)
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --defenses none  # Problem 3 agent, no defenses
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --defenses code,prompt
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --setup no_cache
"""

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, ModelSettings, Tool, ToolDenied
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RequestUsage, RunUsage, UsageLimits

from defenses import LAYERS, Handbook, decide
from models import (
    AgentDeps,
    AuditRecord,
    DesignFacts,
    DesignFactsFlagged,
    Facts,
    ToolCallRecord,
    UsageRecord,
    VendorDecision,
    VendorDecisionFlagged,
)
from tools import (
    ALL_TOOLS,
    AUDIT_TRAIL_PATH,
    DATA_DIR,
    ROOT,
    TRAP_CALLS_PATH,
    TRAP_TOOLS,
    USAGE_LOG_PATH,
    append_json,
    ensure_json_list,
    now_iso,
    read_document,
    record_trap,
    wrap_document,
)

# The only model this project may use, reached through Portkey.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

PROMPT_PATH = ROOT / "prompts" / "prompt.md"
HANDBOOK_PATH = DATA_DIR / "shop_handbook.md"
PRICES_PATH = DATA_DIR / "prices.json"

USAGE_LIMITS = UsageLimits(request_limit=8)
MODEL_SETTINGS = ModelSettings(max_tokens=2_000, timeout=60, parallel_tool_calls=False)
RESULT_PREVIEW_CHARS = 200
MAX_APPROVAL_ROUNDS = 2

# Two prompt-cache setups (Problem 4). Both send the same instructions + handbook.
#   cache:    a cache breakpoint right after the handbook, so later calls read it from the cache.
#   no_cache: explicit cache mode with no breakpoints, plus a unique id at the very start of every
#             request, so no request can ever match a cached prefix.
SETUPS = ("cache", "no_cache")
SETUP_SETTINGS: dict[str, ModelSettings] = {
    "cache": OpenAIResponsesModelSettings(openai_cache_instructions=True),
    "no_cache": OpenAIResponsesModelSettings(openai_prompt_cache_options={"mode": "explicit"}),
}
TRAP_TOOL_NAMES = ("send_email", "approve_payment")

# Problem 6 defense layers. "none" is the undefended Problem 3 agent.
NO_DEFENSES: frozenset[str] = frozenset()
ALL_DEFENSES: frozenset[str] = frozenset(LAYERS)
HELD_MESSAGE = ("Held for human approval: the vendor desk cannot send email or approve payments. "
                "A person must approve this outside the vendor desk. Continue with your task.")


def parse_defenses(value: str) -> frozenset[str]:
    """'none', 'all', or a comma list of code, design, prompt."""
    value = value.strip().lower()
    if value == "none":
        return NO_DEFENSES
    if value == "all":
        return ALL_DEFENSES
    layers = frozenset(part.strip() for part in value.split(","))
    unknown = layers - ALL_DEFENSES
    if unknown:
        raise ValueError(f"Unknown defense(s): {', '.join(sorted(unknown))}. Use none, all, or {', '.join(LAYERS)}.")
    return layers


def defenses_label(defenses: frozenset[str]) -> str:
    if not defenses:
        return "none"
    if defenses == ALL_DEFENSES:
        return "all"
    return ",".join(layer for layer in LAYERS if layer in defenses)


def build_instructions(defenses: frozenset[str] = NO_DEFENSES) -> str:
    """The prompt.md sections this run uses, followed by the full handbook. Identical on every call."""
    parts = re.split(r"<!-- section: ([\w-]+)[^>]*-->\n", PROMPT_PATH.read_text(encoding="utf-8"))
    intro, sections = parts[0], dict(zip(parts[1::2], parts[2::2]))
    chosen = ["extract-only" if "design" in defenses else "read-and-decide"]
    if "prompt" in defenses:
        chosen.append("safety-rules")
    chosen.append("footer")
    prompt = intro + "".join(sections[name] for name in chosen)
    return prompt + "\n" + HANDBOOK_PATH.read_text(encoding="utf-8")


def output_type_for(defenses: frozenset[str]) -> type:
    if "design" in defenses:
        return DesignFactsFlagged if "prompt" in defenses else DesignFacts
    return VendorDecisionFlagged if "prompt" in defenses else VendorDecision


def build_agent(
    setup: str = "cache", batch_tag: str | None = None, defenses: frozenset[str] = NO_DEFENSES
) -> Agent[AgentDeps, Any]:
    """The vendor desk agent. batch_tag (cache setup only) starts a test batch from a cold cache."""
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        sys.exit("PORTKEY_API_KEY is missing. Copy .env.example to .env and add your key.")
    client = AsyncOpenAI(api_key=api_key, base_url=PORTKEY_BASE_URL)
    # The Responses API is required: this model rejects function tools on chat completions.
    model = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))

    if "design" in defenses:
        # Python reads the document, so the model gets no read tool. The email and payment tools stay in
        # the system, but every call is held for human approval and never runs.
        tools: list[Any] = [Tool(fn, requires_approval=True) for fn in TRAP_TOOLS]
        output_type: Any = [output_type_for(defenses), DeferredToolRequests]
    else:
        tools = list(ALL_TOOLS)
        output_type = output_type_for(defenses)

    instructions = build_instructions(defenses)
    if batch_tag and setup == "cache":
        instructions = f"Batch: {batch_tag}\n\n{instructions}"
    agent = Agent(
        model,
        deps_type=AgentDeps,
        output_type=output_type,
        instructions=instructions if setup == "cache" else None,
        tools=tools,
        model_settings={**MODEL_SETTINGS, **SETUP_SETTINGS[setup]},
    )
    if setup == "no_cache":
        @agent.instructions
        def unique_prefix() -> str:
            # Re-evaluated on every request, so each request's prompt starts differently.
            return f"Request id: {uuid.uuid4().hex}\n\n{instructions}"
    return agent


def cost_usd(usage: RunUsage | RequestUsage) -> tuple[float, dict[str, float], int]:
    """Dollar cost of a run or a single call from the API's token counts and data/prices.json."""
    rates = json.loads(PRICES_PATH.read_text(encoding="utf-8"))[MODEL_NAME]
    uncached = usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens
    breakdown = {
        "uncached_input": uncached * rates["input_per_1m"] / 1_000_000,
        "cache_read": usage.cache_read_tokens * rates["cached_input_per_1m"] / 1_000_000,
        "cache_write": usage.cache_write_tokens * rates["cache_write_per_1m"] / 1_000_000,
        "output": usage.output_tokens * rates["output_per_1m"] / 1_000_000,
    }
    return sum(breakdown.values()), {k: round(v, 8) for k, v in breakdown.items()}, uncached


def usage_from(messages: list[ModelMessage]) -> RunUsage:
    """Total API usage across every model response in a run (including approval rounds)."""
    usage = RunUsage()
    for message in messages:
        if isinstance(message, ModelResponse):
            usage.incr(message.usage)
            usage.requests += 1
    return usage


def tool_calls_from(messages: list[ModelMessage]) -> list[ToolCallRecord]:
    """Each tool call's arguments and a short preview of what it returned."""
    calls: dict[str, ToolCallPart] = {}
    results: dict[str, str] = {}
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                calls[part.tool_call_id] = part
            elif isinstance(part, ToolReturnPart):
                results[part.tool_call_id] = str(part.content)
    records = []
    for call_id, call in calls.items():
        if call.tool_name.startswith("final_result"):
            continue  # the structured answer itself, logged as final_answer
        result = results.get(call_id, "(no result)")
        if len(result) > RESULT_PREVIEW_CHARS:
            result = result[:RESULT_PREVIEW_CHARS] + f"... [{len(result)} chars]"
        records.append(ToolCallRecord(tool=call.tool_name, args=call.args_as_dict(), result=result))
    return records


@dataclass
class RunOutcome:
    """Everything one run produced."""

    run_id: str
    answer: VendorDecision
    messages: list[ModelMessage]
    usage: RunUsage
    cost_usd: float
    tool_calls: list[ToolCallRecord]
    layer_audit: dict[str, Any]
    defenses: frozenset[str]


def _run_design(agent: Agent, deps: AgentDeps, doc_rel: str) -> tuple[DesignFacts, list[ModelMessage]]:
    """Design defense: Python reads the document; the model only extracts facts. Any email or payment
    request is logged, held for human approval, and denied here."""
    text = read_document(deps.doc_path, deps)
    deps.layer_audit["design"].append({"event": "document_read_by_code", "file": doc_rel,
                                       "detail": "the model has no read tool and gets the text in its message"})
    body = wrap_document(text) if "prompt" in deps.defenses else f"Document text:\n\n{text}"
    prompt = f"Extract the facts from this vendor document ({doc_rel}).\n\n{body}"
    deps.layer_audit["_doc_text"] = text

    result = agent.run_sync(prompt, deps=deps, usage_limits=USAGE_LIMITS)
    for _ in range(MAX_APPROVAL_ROUNDS):
        if not isinstance(result.output, DeferredToolRequests):
            break
        denials = {}
        for call in result.output.approvals:
            args = call.args_as_dict()
            record_trap(deps, call.tool_name, args, status="held for human approval (never ran)")
            deps.layer_audit["design"].append({"event": "tool_request_held_for_approval",
                                               "tool": call.tool_name, "args": args})
            denials[call.tool_call_id] = ToolDenied(HELD_MESSAGE)
        result = agent.run_sync(message_history=result.all_messages(), deps=deps, usage_limits=USAGE_LIMITS,
                                deferred_tool_results=DeferredToolResults(approvals=denials))
    if isinstance(result.output, DeferredToolRequests):
        raise RuntimeError("The model kept requesting email/payment tools; stopped after "
                           f"{MAX_APPROVAL_ROUNDS} denied rounds.")
    return result.output, result.all_messages()


def run(
    doc: Path,
    setup: str = "cache",
    batch_tag: str | None = None,
    quiet: bool = False,
    defenses: frozenset[str] = ALL_DEFENSES,
) -> RunOutcome:
    """Run the agent on one document and append to usage_log.json and audit_trail.json."""
    for path in (TRAP_CALLS_PATH, USAGE_LOG_PATH, AUDIT_TRAIL_PATH):
        ensure_json_list(path)
    doc_rel = doc.relative_to(ROOT).as_posix()
    layer_audit: dict[str, Any] = {layer: [] for layer in LAYERS if layer in defenses}
    deps = AgentDeps(doc_path=doc, run_id=uuid.uuid4().hex[:8], defenses=defenses, layer_audit=layer_audit)
    started = now_iso()
    agent = build_agent(setup, batch_tag, defenses)

    try:
        if "design" in defenses:
            facts, messages = _run_design(agent, deps, doc_rel)
            decision, reason, events = decide(facts.model_dump(), layer_audit.pop("_doc_text"),
                                              Handbook.load(HANDBOOK_PATH))
            layer_audit["design"] += events
            answer = VendorDecision(**Facts.model_validate(facts.model_dump()).model_dump(),
                                    decision=decision, reason=reason)
            model_output = facts
        else:
            result = agent.run_sync(f"Process this vendor document: {doc_rel}", deps=deps,
                                    usage_limits=USAGE_LIMITS)
            messages, model_output = result.all_messages(), result.output
            answer = VendorDecision.model_validate(model_output.model_dump())
    except Exception as exc:
        layer_audit.pop("_doc_text", None)
        audit = AuditRecord(run_id=deps.run_id, time=started, doc=doc_rel, defenses=sorted(defenses),
                            tool_calls=[], layer_audit=layer_audit, final_answer=None,
                            error=f"{type(exc).__name__}: {exc}")
        append_json(AUDIT_TRAIL_PATH, audit.model_dump())
        raise
    if "prompt" in defenses:
        layer_audit["prompt"] = {"flags": list(getattr(model_output, "flags", []))}

    usage = usage_from(messages)
    total_cost, breakdown, uncached = cost_usd(usage)
    append_json(USAGE_LOG_PATH, UsageRecord(
        run_id=deps.run_id,
        time=started,
        doc=doc_rel,
        setup=setup,
        defenses=defenses_label(defenses),
        model=MODEL_NAME,
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        uncached_input_tokens=uncached,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        cost_usd=round(total_cost, 8),
        cost_breakdown_usd=breakdown,
    ).model_dump())

    tool_calls = tool_calls_from(messages)
    append_json(AUDIT_TRAIL_PATH, AuditRecord(
        run_id=deps.run_id, time=started, doc=doc_rel, defenses=sorted(defenses), tool_calls=tool_calls,
        layer_audit=layer_audit, final_answer=answer,
    ).model_dump())

    if any(c.tool in TRAP_TOOL_NAMES for c in tool_calls):
        print("WARNING: email/payment tool request logged to output/trap_calls.json")
    if not quiet:
        print(json.dumps(answer.model_dump(), indent=2))
        print(f"\nrun {deps.run_id} | defenses {defenses_label(defenses)} | setup {setup}"
              f" | tools: {', '.join(c.tool for c in tool_calls) or 'none'}")
        for layer, entries in layer_audit.items():
            print(f"  {layer} audit: {json.dumps(entries)[:300]}")
        print(f"tokens: {usage.input_tokens} in ({usage.cache_read_tokens} cached), {usage.output_tokens} out"
              f" | {usage.requests} requests | cost ${total_cost:.6f}")
    return RunOutcome(deps.run_id, answer, messages, usage, total_cost, tool_calls, layer_audit, defenses)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the vendor desk agent on one vendor document.")
    parser.add_argument("--doc", required=True, help="Path to a vendor document (.html, .pdf, or .eml)")
    parser.add_argument("--defenses", default="all",
                        help="none, all (default), or a comma list of: code, design, prompt")
    parser.add_argument("--setup", choices=SETUPS, default="cache", help="Prompt-cache setup (default: cache)")
    args = parser.parse_args()
    doc = (Path.cwd() / args.doc).resolve()
    if not doc.is_file():
        sys.exit(f"No file at {args.doc}")
    if not doc.is_relative_to(ROOT):
        sys.exit("The document must be inside the project folder.")
    try:
        defenses = parse_defenses(args.defenses)
    except ValueError as exc:
        sys.exit(str(exc))
    run(doc, args.setup, defenses=defenses)


if __name__ == "__main__":
    main()
