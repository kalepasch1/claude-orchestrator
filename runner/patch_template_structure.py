#!/usr/bin/env python3
"""Structural analysis of patch templates — shape only, never content.

`patch_templates.build()` emits a template whose *shape* is a contract: a
`PATCH TEMPLATE <id>` header, labelled `Key: value` lines, a numbered slot list,
an optional prior-patterns section, and a `[patch-template:<id>]` marker that
downstream code greps for. Consumers (`inject_prompt`, `pre_claim_hook`,
`lookup`, the quarantine gate that rejects hex-only stubs) all depend on that
shape, but nothing asserts it — so a reworded builder silently breaks them.

This module observes the structure and reports it. It deliberately does **not**
adapt, rewrite, or reuse any template content: `observe()` returns facts about
prefixes, suffixes, section headers, slot numbering, comment style, marker
format and commit-message format, and `report()` renders those facts as a list
of observations.

Fail-soft throughout: None/empty/binary input yields an empty observation set
rather than an exception, so an analysis pass can never wedge the runner.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HEADER = re.compile(r"^PATCH TEMPLATE\s+([0-9a-f]{6,40})\s*$", re.I)
MARKER = re.compile(r"\[patch-template:([0-9a-f]{6,40})\]")
LABEL = re.compile(r"^([A-Z][A-Za-z /-]{2,40}):\s*(.*)$")
NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
BULLET = re.compile(r"^\s*[-*•]\s+(.+)$")
SECTION = re.compile(r"^([A-Z][A-Za-z /-]{2,40}):\s*$")
COMMENT = re.compile(r"^\s*(#|//|/\*|\*)\s?(.*)$")
# Matched with `search`, not `match`: a template often names the commit format
# inside a slot ("1. commit as: agent: <slug>"), not on a line of its own.
COMMIT_MSG = re.compile(
    r"\b(agent|feat|fix|chore|docs|refactor|test|perf|build|ci)"
    r"(?:\(([^)]*)\))?:[ \t]+(\S.*)$"
)
HEX_ONLY = re.compile(r"^[0-9a-fA-F\s]+$")
SIM = re.compile(r"\bsim(?:ilarity)?=([0-9.]+)")
SOURCE_LINE = re.compile(r"^\s*[-*]\s*([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\s")


def _text(value):
    """Coerce anything to str. Never raises."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _empty():
    return {
        "template_id": "",
        "header_prefix": "",
        "marker_suffix": "",
        "marker_matches_header": False,
        "labels": [],
        "sections": [],
        "slot_numbering": "none",
        "slot_count": 0,
        "slots": [],
        "bullet_count": 0,
        "comment_style": "none",
        "commit_message_format": "none",
        "sources": [],
        "similarity_values": [],
        "line_count": 0,
        "is_hex_only_stub": False,
        "well_formed": False,
    }


def _slot_numbering(numbers):
    if not numbers:
        return "none"
    if numbers == list(range(1, len(numbers) + 1)):
        return "sequential-from-1"
    if numbers == list(range(0, len(numbers))):
        return "sequential-from-0"
    if sorted(numbers) == numbers:
        return "ascending-with-gaps"
    return "unordered"


def _comment_style(lines):
    hashes = sum(1 for ln in lines if ln.lstrip().startswith("#"))
    slashes = sum(1 for ln in lines if ln.lstrip().startswith("//"))
    blocks = sum(1 for ln in lines if ln.lstrip().startswith(("/*", "*/")))
    ranked = sorted((("hash", hashes), ("double-slash", slashes), ("block", blocks)),
                    key=lambda kv: -kv[1])
    if ranked[0][1] == 0:
        return "none"
    if ranked[0][1] == ranked[1][1]:
        return "mixed"
    return ranked[0][0]


def _commit_format(lines):
    """Classify any commit-message-shaped line present in the template."""
    for ln in lines:
        m = COMMIT_MSG.search(ln.strip())
        if m:
            kind, scope, _subject = m.groups()
            if kind == "agent":
                return "agent: <slug>"
            return f"{kind}({scope}): <subject>" if scope else f"{kind}: <subject>"
    return "none"


def observe(body):
    """Return structural facts about one patch template body.

    Pure observation — no template content is adapted or reused. Returns the
    empty observation set on None/empty/non-text input.
    """
    # A template body is text. Numbers, lists and dicts are caller error, not a
    # one-line template — coercing them would report bogus structure.
    if not isinstance(body, (str, bytes, bytearray)):
        return _empty()
    body = _text(bytes(body) if isinstance(body, bytearray) else body)
    if not body.strip():
        return _empty()
    try:
        obs = _empty()
        lines = body.splitlines()
        obs["line_count"] = len(lines)
        stripped = body.strip()
        obs["is_hex_only_stub"] = bool(HEX_ONLY.match(stripped)) and len(stripped) > 8

        header_id = ""
        for ln in lines:
            m = HEADER.match(ln.strip())
            if m:
                header_id = m.group(1)
                obs["header_prefix"] = "PATCH TEMPLATE <id>"
                break

        marker = MARKER.search(body)
        marker_id = marker.group(1) if marker else ""
        if marker:
            obs["marker_suffix"] = "[patch-template:<id>]"
        obs["template_id"] = header_id or marker_id
        obs["marker_matches_header"] = bool(header_id and marker_id and header_id == marker_id)

        numbers = []
        for ln in lines:
            if HEADER.match(ln.strip()):
                continue
            sec = SECTION.match(ln.rstrip())
            if sec:
                if sec.group(1) not in obs["sections"]:
                    obs["sections"].append(sec.group(1))
                continue
            lab = LABEL.match(ln.rstrip())
            if lab and lab.group(2).strip():
                if lab.group(1) not in obs["labels"]:
                    obs["labels"].append(lab.group(1))
                continue
            num = NUMBERED.match(ln)
            if num:
                numbers.append(int(num.group(1)))
                obs["slots"].append(num.group(2).strip()[:120])
                continue
            if BULLET.match(ln):
                obs["bullet_count"] += 1
                src = SOURCE_LINE.match(ln)
                if src:
                    ref = f"{src.group(1)}/{src.group(2)}"
                    if ref not in obs["sources"]:
                        obs["sources"].append(ref)

        obs["slot_count"] = len(numbers)
        obs["slot_numbering"] = _slot_numbering(numbers)
        obs["comment_style"] = _comment_style(lines)
        obs["commit_message_format"] = _commit_format(lines)
        obs["similarity_values"] = [v for v in SIM.findall(body)][:10]
        obs["well_formed"] = bool(
            obs["header_prefix"] and obs["labels"] and obs["slot_count"] >= 1
            and not obs["is_hex_only_stub"]
        )
        return obs
    except Exception:
        return _empty()


def report(body):
    """Render `observe()` as a flat list of human-readable observations."""
    obs = observe(body)
    if not obs["line_count"]:
        return []
    out = []
    if obs["header_prefix"]:
        out.append(f"prefix: first line is `{obs['header_prefix']}`"
                   + (f" (id={obs['template_id']})" if obs["template_id"] else ""))
    else:
        out.append("prefix: no `PATCH TEMPLATE <id>` header line")
    if obs["marker_suffix"]:
        out.append(f"suffix: trailing marker `{obs['marker_suffix']}`; "
                   f"header/marker ids {'agree' if obs['marker_matches_header'] else 'DISAGREE'}")
    else:
        out.append("suffix: no `[patch-template:<id>]` marker — downstream greps will miss it")
    out.append("labels: " + (", ".join(f"`{lbl}:`" for lbl in obs["labels"]) or "none"))
    out.append("sections: " + (", ".join(f"`{s}:`" for s in obs["sections"]) or "none"))
    out.append(f"slots: {obs['slot_count']} numbered item(s), numbering={obs['slot_numbering']}")
    out.append(f"bullets: {obs['bullet_count']} `- ` item(s)")
    if obs["sources"]:
        out.append("prior-source refs: " + ", ".join(obs["sources"][:6]))
    if obs["similarity_values"]:
        out.append("similarity annotations: " + ", ".join(obs["similarity_values"]))
    out.append(f"comment style: {obs['comment_style']}")
    out.append(f"commit message format: {obs['commit_message_format']}")
    if obs["is_hex_only_stub"]:
        out.append("WARNING: body is hex-only — this is a binary stub, not a readable template")
    out.append(f"well-formed: {obs['well_formed']} ({obs['line_count']} lines)")
    return out


def compare(bodies):
    """Structural facts shared by every template in `bodies` vs. those that vary.

    Useful for spotting drift: a key under `varies` means the builder is not
    emitting a stable shape across tasks.
    """
    observed = [observe(b) for b in (bodies or [])]
    observed = [o for o in observed if o["line_count"]]
    if not observed:
        return {"common": {}, "varies": [], "count": 0}
    keys = ("header_prefix", "marker_suffix", "slot_numbering", "slot_count",
            "comment_style", "commit_message_format")
    common, varies = {}, []
    for k in keys:
        values = {o[k] for o in observed}
        if len(values) == 1:
            common[k] = observed[0][k]
        else:
            varies.append(k)
    return {"common": common, "varies": sorted(varies), "count": len(observed)}


if __name__ == "__main__":
    text = sys.stdin.read()
    for line in report(text):
        print("- " + line)
