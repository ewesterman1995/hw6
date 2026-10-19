"""Problem 6 defenses for the vendor desk agent.

Layer 1 (code): read only what a person would see. Hidden text is removed before the model sees the
                document, invisible characters are stripped, and every removal is logged.
Layer 2 (design): the model only extracts facts. Python applies the four handbook checks, checks the
                vendor's identity against the handbook's contact domains, and holds any email or payment
                request for human approval.
Layer 3 (prompt) lives in prompts/prompt.md (the "safety-rules" section).

Every function returns audit events (plain dicts) alongside its result, so each layer leaves a record.
"""

import email
import re
import unicodedata
from dataclasses import dataclass, field
from email import policy
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pypdf import PdfReader

LAYERS = ("code", "design", "prompt")
MAX_DOC_CHARS = 20_000  # a real quote is a few hundred characters; anything far bigger is padding

# ---------------------------------------------------------------------------
# Layer 1: code. Read only what a person can see.
# ---------------------------------------------------------------------------

INVISIBLE_CHARS = re.compile(r"[­͏؜ᅟᅠ឴឵᠎​-‏‪-‮"
                             r"⁠-⁤⁪-⁯﻿]")
WRAPPER_TAGS = re.compile(r"</?\s*vendor_document[^>]*>", re.I)


def clean_characters(text: str) -> tuple[str, list[dict]]:
    """Strip invisible characters, normalize lookalike forms (NFKC), and cap the length."""
    events = []
    stripped, n = INVISIBLE_CHARS.subn("", text)
    if n:
        events.append({"event": "invisible_characters_stripped", "count": n})
    normalized = unicodedata.normalize("NFKC", stripped)
    if normalized != stripped:
        events.append({"event": "characters_normalized", "detail": "NFKC lookalike forms replaced"})
    unwrapped, n = WRAPPER_TAGS.subn("", normalized)
    if n:
        events.append({"event": "fake_wrapper_tags_removed", "count": n})
    if len(unwrapped) > MAX_DOC_CHARS:
        events.append({"event": "document_truncated", "original_chars": len(unwrapped), "kept_chars": MAX_DOC_CHARS})
        unwrapped = unwrapped[:MAX_DOC_CHARS]
    return unwrapped, events


# ---------- HTML ----------

_HIDDEN_CSS = [
    (re.compile(r"display\s*:\s*none", re.I), "display:none"),
    (re.compile(r"visibility\s*:\s*(hidden|collapse)", re.I), "visibility:hidden"),
    (re.compile(r"opacity\s*:\s*0(\.0*)?\s*(;|$)", re.I), "opacity:0"),
    (re.compile(r"font-size\s*:\s*(0|[01](\.\d+)?)\s*(px|pt)?\s*(;|$)", re.I), "font size 0-1"),
    (re.compile(r"(?<![-\w])color\s*:\s*(#fff\b|#ffffff\b|white\b|rgb\(\s*25[0-5]\s*,\s*25[0-5]\s*,\s*25[0-5]\s*\))",
                re.I), "white text"),
    (re.compile(r"text-indent\s*:\s*-\d{3,}", re.I), "text pushed off screen"),
    (re.compile(r"(left|top)\s*:\s*-\d{3,}", re.I), "positioned off screen"),
    (re.compile(r"(height|width)\s*:\s*0(px)?\s*(;|$)", re.I), "zero-size box"),
    (re.compile(r"clip\s*:\s*rect\(\s*0", re.I), "clipped away"),
]
_SKIP_TAGS = {"script", "style", "noscript", "template", "head"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_BLOCK_TAGS = {"p", "div", "tr", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer", "table",
               "title", "section", "article", "ul", "ol"}


_NAMED_COLORS = {"white": (255, 255, 255), "black": (0, 0, 0), "transparent": None}
COLOR_MATCH_TOLERANCE = 24  # max per-channel difference (0-255) for text to count as "same color as background"


def _parse_color(value: str) -> tuple[int, int, int] | None:
    value = value.strip().lower()
    if value in _NAMED_COLORS:
        return _NAMED_COLORS[value]
    if m := re.fullmatch(r"#([0-9a-f]{3})", value):
        return tuple(int(ch * 2, 16) for ch in m.group(1))  # type: ignore[return-value]
    if m := re.fullmatch(r"#([0-9a-f]{6})", value):
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if m := re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)[^)]*\)", value):
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def _style_colors(style: str) -> tuple[tuple[int, int, int] | None, tuple[int, int, int] | None]:
    """(text color, background color) set by an inline style, if any."""
    color = bg = None
    for prop, val in re.findall(r"([\w-]+)\s*:\s*([^;]+)", style or ""):
        prop = prop.lower()
        if prop == "color":
            color = _parse_color(val)
        elif prop in ("background", "background-color"):
            token = re.search(r"#[0-9a-fA-F]{3,6}\b|rgba?\([^)]*\)|\b[a-z]+\b", val)
            bg = _parse_color(token.group(0)) if token else None
    return color, bg


def _same_color(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    return max(abs(x - y) for x, y in zip(a, b)) <= COLOR_MATCH_TOLERANCE


def _hidden_reason(style: str) -> str | None:
    for pattern, reason in _HIDDEN_CSS:
        if pattern.search(style or ""):
            return reason
    return None


def _css_rules(html: str) -> dict[str, str]:
    """Selectors (.class, #id, tag) that a <style> block hides, mapped to the reason."""
    rules = {}
    for block in re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I):
        for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", block):
            reason = _hidden_reason(body)
            if reason:
                for sel in selectors.split(","):
                    rules[sel.strip().lower()] = reason
    return rules


class _VisibleHTML(HTMLParser):
    """Collects visible text and, separately, text a browser would not show."""

    def __init__(self, css_rules: dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self.css_rules = css_rules
        self.stack: list[tuple[str, str | None]] = []  # (tag, hidden reason)
        self.colors: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []  # (text, background) per element
        self.visible: list[str] = []
        self.hidden: dict[str, list[str]] = {}

    def _current_hidden(self) -> str | None:
        return next((reason for _, reason in reversed(self.stack) if reason), None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        reason = None
        if tag in _SKIP_TAGS:
            reason = f"<{tag}> content"
        elif "hidden" in a:
            reason = "hidden attribute"
        else:
            reason = _hidden_reason(a.get("style", ""))
            selectors = [tag] + [f".{c.lower()}" for c in a.get("class", "").split()]
            if a.get("id"):
                selectors.append(f"#{a['id'].lower()}")
            reason = reason or next((self.css_rules[s] for s in selectors if s in self.css_rules), None)
        # Text colored like the background behind it is invisible, whatever the color (not just white).
        parent_color, parent_bg = self.colors[-1] if self.colors else ((0, 0, 0), (255, 255, 255))
        own_color, own_bg = _style_colors(a.get("style", ""))
        color, bg = own_color or parent_color, own_bg or parent_bg
        if reason is None and (own_color or own_bg) and _same_color(color, bg):
            reason = "text colored like its background"
        if tag in ("td", "th"):
            self.visible.append(" | ")
        elif tag in _BLOCK_TAGS:
            self.visible.append("\n")
        if tag not in _VOID_TAGS:
            self.stack.append((tag, reason))
            self.colors.append((color, bg))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                del self.colors[i:]
                break
        if tag in _BLOCK_TAGS:
            self.visible.append("\n")

    def handle_data(self, data: str) -> None:
        reason = self._current_hidden()
        if reason is None:
            self.visible.append(data)
        elif data.strip() and not reason.startswith("<"):
            self.hidden.setdefault(reason, []).append(data.strip())

    def handle_comment(self, data: str) -> None:
        if data.strip():
            self.hidden.setdefault("HTML comment", []).append(data.strip())


def _readable(texts: list[str]) -> str:
    """Hidden text for the audit log, with invisible characters removed so a person can read it."""
    return INVISIBLE_CHARS.sub("", " ".join(texts))


def _tidy(text: str) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def visible_html(html: str, where: str = "HTML") -> tuple[str, list[dict]]:
    parser = _VisibleHTML(_css_rules(html))
    parser.feed(html)
    events = [{"event": "hidden_text_removed", "where": where, "how_hidden": reason, "text": _readable(texts)}
              for reason, texts in parser.hidden.items()]
    return _tidy("".join(parser.visible)), events


# ---------- PDF ----------

MIN_PDF_FONT_PT = 4.0


def _near_white(fill: tuple[float, ...], space: str) -> bool:
    if space == "cmyk":
        return all(v <= 0.08 for v in fill)
    return all(v >= 0.92 for v in fill)


def _multiply(m1: list[float], m2: list[float]) -> list[float]:
    a, b, c, d, e, f = m1
    g, h, i, j, k, l = m2
    return [a * g + b * i, a * h + b * j, c * g + d * i, c * h + d * j, e * g + f * i + k, e * h + f * j + l]


_FILL_OPS = {b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
_PATH_END_OPS = {b"n", b"S", b"s"}


def _apply(m: list[float], x: float, y: float) -> tuple[float, float]:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def visible_pdf(path: Path) -> tuple[str, list[dict]]:
    """Visible text of a PDF: drops tiny, white, invisible-mode, and off-page text, and text covered by a
    filled shape drawn on top of it."""
    events: list[dict] = []
    pages = []
    for page_no, page in enumerate(PdfReader(path).pages, start=1):
        box = page.mediabox
        x0, y0, x1, y1 = float(box.left), float(box.bottom), float(box.right), float(box.top)
        state: dict[str, Any] = {"fill": (0.0, 0.0, 0.0), "space": "rgb", "mode": 0, "order": 0}
        chunks: list[dict[str, Any]] = []  # text pieces in reading order
        pending_rects: list[tuple[float, float, float, float]] = []
        filled_rects: list[dict[str, Any]] = []  # shapes painted on the page, with when they were painted

        def before(op: bytes, args: list, cm: list, tm: list) -> None:
            state["order"] += 1
            if op == b"rg":
                state["fill"], state["space"] = tuple(float(v) for v in args), "rgb"
            elif op == b"g":
                state["fill"], state["space"] = (float(args[0]),) * 3, "rgb"
            elif op == b"k":
                state["fill"], state["space"] = tuple(float(v) for v in args), "cmyk"
            elif op == b"Tr":
                state["mode"] = int(args[0])
            elif op == b"re":
                rx, ry, rw, rh = (float(v) for v in args)
                corners = [_apply(list(cm), cx, cy) for cx, cy in ((rx, ry), (rx + rw, ry + rh))]
                xs, ys = [c[0] for c in corners], [c[1] for c in corners]
                pending_rects.append((min(xs), min(ys), max(xs), max(ys)))
            elif op in _FILL_OPS:
                filled_rects.extend({"box": r, "order": state["order"]} for r in pending_rects)
                pending_rects.clear()
            elif op in _PATH_END_OPS:
                pending_rects.clear()

        def on_text(text: str, cm: list, tm: list, font: Any, size: float) -> None:
            state["order"] += 1
            if not text.strip():
                chunks.append({"text": text, "reason": None})
                return
            m = _multiply(list(tm), list(cm))
            scale = (m[0] ** 2 + m[1] ** 2) ** 0.5 or 1.0
            effective = float(size) * scale
            x, y = m[4], m[5]
            if state["mode"] == 3:
                reason = "invisible text mode"
            elif effective < MIN_PDF_FONT_PT:
                reason = f"{effective:g} pt font"
            elif _near_white(state["fill"], state["space"]):
                reason = "white text"
            elif not (x0 - 5 <= x <= x1 + 5 and y0 - 5 <= y <= y1 + 5):
                reason = f"placed off the page (x={x:g}, y={y:g})"
            else:
                reason = None
            width = 0.5 * effective * len(text.strip())  # rough width of the printed text
            chunks.append({"text": text, "reason": reason, "order": state["order"],
                           "points": [(x + 1, y + 0.3 * effective), (x + width / 2, y + 0.3 * effective)]})

        page.extract_text(visitor_operand_before=before, visitor_text=on_text)

        # Text is hidden if a filled shape painted *after* it covers where it sits.
        for chunk in chunks:
            if chunk["reason"] is None and chunk["text"].strip():
                for shape in filled_rects:
                    bx0, by0, bx1, by1 = shape["box"]
                    if shape["order"] > chunk["order"] and all(
                            bx0 <= px <= bx1 and by0 <= py <= by1 for px, py in chunk["points"]):
                        chunk["reason"] = "covered by a shape drawn on top of it"
                        break

        visible: list[str] = []
        hidden: dict[str, list[str]] = {}
        for chunk in chunks:
            if chunk["reason"] is None:
                visible.append(chunk["text"])
            else:
                hidden.setdefault(chunk["reason"], []).append(chunk["text"].strip())
                if not chunk["text"].endswith("\n"):
                    visible.append("\n")
        pages.append("".join(visible))
        events += [{"event": "hidden_text_removed", "where": f"PDF page {page_no}", "how_hidden": reason,
                    "text": _readable(texts)} for reason, texts in hidden.items()]
    return _tidy("\n".join(pages)), events


# ---------- Email ----------

def visible_eml(path: Path) -> tuple[str, list[dict]]:
    """Headers + the plain-text body. If the email also has an HTML version, log what it hides."""
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    events: list[dict] = []
    headers = [f"{name}: {msg[name]}" for name in ("From", "Reply-To", "To", "Subject", "Date") if msg[name]]
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    if plain is not None:
        body = _tidy(plain.get_content())
        if html is not None:
            _, html_events = visible_html(html.get_content(), where="email HTML version (not used)")
            events += html_events
    elif html is not None:
        body, events = visible_html(html.get_content(), where="email HTML body")
    else:
        body = ""
    attachments = [part.get_filename() or part.get_content_type() for part in msg.iter_attachments()]
    if attachments:
        events.append({"event": "attachments_not_read", "files": attachments})
    return "\n".join(headers) + "\n\n" + body, events


def read_visible(path: Path) -> tuple[str, list[dict]]:
    """Layer 1 entry point: the document as a person would see it, plus what was removed."""
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        text, events = visible_html(path.read_text(encoding="utf-8", errors="replace"))
    elif suffix == ".pdf":
        text, events = visible_pdf(path)
    elif suffix == ".eml":
        text, events = visible_eml(path)
    else:
        raise ValueError(f"Unsupported file type {suffix}")
    text, char_events = clean_characters(text)
    return text, events + char_events


# ---------------------------------------------------------------------------
# Layer 2: design. Python applies the handbook, not the model.
# ---------------------------------------------------------------------------

MAX_LEAD_TIME_DAYS = 21
MAX_MIN_ORDER = 600


def _norm_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).casefold()
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


@dataclass
class Handbook:
    approved: dict[str, dict[str, str]] = field(default_factory=dict)  # normalized name -> {name, code, domain}
    removed: dict[str, str] = field(default_factory=dict)  # normalized name -> status
    max_cost: dict[str, float] = field(default_factory=dict)  # SKU -> max unit cost
    item_name: dict[str, str] = field(default_factory=dict)  # SKU -> catalogue item name

    @classmethod
    def load(cls, path: Path) -> "Handbook":
        text = path.read_text(encoding="utf-8")
        sections = re.split(r"^## ", text, flags=re.M)
        hb = cls()
        for section in sections:
            rows = [[c.strip() for c in line.strip().strip("|").split("|")]
                    for line in section.splitlines() if line.startswith("|") and not line.startswith("|---")]
            if section.startswith("5. Approved vendors"):
                for code, name, *_rest in rows[1:]:
                    domain = re.search(r"@([\w.-]+\.\w+)", _rest[-1])
                    hb.approved[_norm_name(name)] = {"name": name, "code": code,
                                                     "domain": domain.group(1).lower() if domain else ""}
            elif section.startswith("6. Removed and pending vendors"):
                for name, status, *_ in rows[1:]:
                    hb.removed[_norm_name(name)] = status
            elif section.startswith("9. Product catalogue"):
                for row in rows[1:]:
                    hb.max_cost[row[0]] = float(row[4].replace("$", "").replace(",", ""))
                    hb.item_name[row[0]] = row[1]
        return hb


EMAIL_DOMAIN = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
ITEM_MATCH_THRESHOLD = 0.5


def items_match(document_item: str, catalogue_item: str) -> bool:
    """Does the item named in the document plausibly describe this catalogue item?"""
    doc_words, cat_words = set(_norm_name(document_item).split()), set(_norm_name(catalogue_item).split())
    if not doc_words or not cat_words:
        return False
    if cat_words <= doc_words or doc_words <= cat_words:
        return True
    return len(doc_words & cat_words) / len(doc_words | cat_words) >= ITEM_MATCH_THRESHOLD


def decide(facts: dict[str, Any], doc_text: str, handbook: Handbook) -> tuple[str, str, list[dict]]:
    """Apply the four purchasing checks (handbook section 4) in code. Returns decision, reason, audit."""
    events: list[dict] = []
    vendor, sku = facts.get("vendor"), facts.get("sku")
    price, lead, minimum = facts.get("unit_price"), facts.get("lead_time_days"), facts.get("min_order")
    key = _norm_name(vendor or "")
    approved = handbook.approved.get(key)

    # Identity: if the document names contact addresses, one must belong to the approved vendor.
    domains = sorted({d.lower() for d in EMAIL_DOMAIN.findall(doc_text) if not d.lower().startswith("campuscustoms")})
    identity_ok = True
    if approved:
        if not domains:
            events.append({"event": "identity_check", "result": "unverified",
                           "detail": f"no contact address in the document for {approved['name']}"})
        elif approved["domain"] in domains:
            events.append({"event": "identity_check", "result": "match", "vendor": approved["name"],
                           "expected_domain": approved["domain"], "found_domains": domains})
        else:
            identity_ok = False
            events.append({"event": "identity_check", "result": "MISMATCH", "vendor": approved["name"],
                           "expected_domain": approved["domain"], "found_domains": domains})

    checks: list[tuple[str, bool, str]] = []
    if key in handbook.removed:
        checks.append(("approved_vendor", False, f"{vendor} is on the removed or pending vendor list"))
    elif not approved:
        checks.append(("approved_vendor", False,
                       f"{vendor or 'the vendor'} is not on the approved vendor list" if vendor
                       else "the document does not name a vendor"))
    elif not identity_ok:
        checks.append(("approved_vendor", False,
                       f"the document's contact domain ({', '.join(domains)}) does not match "
                       f"{approved['name']} ({approved['domain']})"))
    else:
        checks.append(("approved_vendor", True, f"{approved['name']} is approved"))

    # SKU cross-check: the SKU's catalogue item must match the item the document actually quotes.
    # Otherwise a swapped SKU could borrow a higher max unit cost.
    max_cost = handbook.max_cost.get(sku or "")
    document_item = facts.get("item")
    sku_ok = True
    if max_cost is not None:
        catalogue_item = handbook.item_name[sku]
        if not document_item:
            events.append({"event": "sku_item_check", "result": "unverified", "sku": sku,
                           "catalogue_item": catalogue_item, "detail": "the document names no item"})
        elif items_match(document_item, catalogue_item):
            events.append({"event": "sku_item_check", "result": "match", "sku": sku,
                           "catalogue_item": catalogue_item, "document_item": document_item})
        else:
            sku_ok = False
            events.append({"event": "sku_item_check", "result": "MISMATCH", "sku": sku,
                           "catalogue_item": catalogue_item, "document_item": document_item})

    if price is None:
        checks.append(("price", False, "the unit price is not stated"))
    elif max_cost is None:
        checks.append(("price", False, f"SKU {sku or '(none)'} is not in the catalogue"))
    elif not sku_ok:
        checks.append(("price", False,
                       f"SKU {sku} is the {handbook.item_name[sku]} in the catalogue, but the document quotes "
                       f"a {document_item}, so its max unit cost can't be used"))
    else:
        checks.append(("price", price <= max_cost,
                       f"${price:.2f} is {'at or below' if price <= max_cost else 'above'} the "
                       f"${max_cost:.2f} max unit cost for {sku}"))

    if lead is None:
        checks.append(("lead_time", False, "the lead time is not stated"))
    else:
        checks.append(("lead_time", lead <= MAX_LEAD_TIME_DAYS,
                       f"{lead} days is {'within' if lead <= MAX_LEAD_TIME_DAYS else 'over'} the "
                       f"{MAX_LEAD_TIME_DAYS}-day limit"))

    if minimum is None:
        checks.append(("min_order", False, "the minimum order is not stated"))
    else:
        checks.append(("min_order", minimum <= MAX_MIN_ORDER,
                       f"{minimum} units is {'within' if minimum <= MAX_MIN_ORDER else 'over'} the "
                       f"{MAX_MIN_ORDER}-unit limit"))

    events.append({"event": "purchasing_checks",
                   "checks": [{"check": name, "passed": ok, "detail": detail} for name, ok, detail in checks]})
    labels = {"approved_vendor": "Approved vendor", "price": "Price", "lead_time": "Lead time",
              "min_order": "Minimum order"}
    failed = next(((name, detail) for name, ok, detail in checks if not ok), None)
    if failed:
        return "do_not_recommend", f"{labels[failed[0]]} check failed: {failed[1]}.", events
    return "recommend", "All four purchasing checks passed.", events
