#!/usr/bin/env python3
"""Mine a diff for code that should have been a shared helper.

Scope note (this is deliberately *not* `patch_adaptation.py`)
------------------------------------------------------------
`patch_adaptation` looks *outward*: given prior merged diffs, it tells a coder
which existing project helpers to reuse. This module looks *inward*: given one
diff, it finds blocks the diff itself repeats — the same guard written four
times, the same try/except wrapper pasted into every handler — and proposes the
abstraction that would collapse them.

Both answer "reuse instead of writing new code", from opposite directions, and
neither imports the other.

How duplication is detected
---------------------------
Structural fingerprinting, not text equality. Each added block is normalised:
identifiers become `N`, string and numeric literals become `L`, whitespace
collapses. Two blocks that differ only in variable and literal choice therefore
land on the same fingerprint, which is exactly the copy-paste-and-rename case
that text diffing misses.

Signals a fingerprint is worth abstracting:
  * it occurs 2+ times in the diff,
  * the block is at least MIN_LINES long (a one-line repeat is not a helper),
  * the occurrences differ in their concrete tokens (identical text repeated in
    one file is more often a legitimate pattern than an extractable helper —
    it is still reported, at lower confidence).

Fail-soft: every entry point returns an empty result on None/empty/malformed
input and never raises.
"""
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DIFF_GIT = re.compile(r"^diff --git a/(.+?) b/(.+)$")
HUNK = re.compile(r"^@@ ")
PY_DEF = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\(([^)]*)\)")
PY_CLASS = re.compile(r"^\s*class\s+([A-Za-z_][\w]*)")
JS_DEF = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\))"
)
JS_CLASS = re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")
IDENT = re.compile(r"[A-Za-z_$][\w$]*")
STRING = re.compile(r"(\"[^\"]*\"|'[^']*'|`[^`]*`)")
NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")

#: Words that carry structure, so they must survive normalisation.
KEYWORDS = {
    "if", "else", "elif", "for", "while", "try", "except", "finally", "with",
    "return", "raise", "def", "class", "import", "from", "as", "in", "not",
    "and", "or", "is", "none", "true", "false", "await", "async", "yield",
    "function", "const", "let", "var", "catch", "throw", "new", "typeof",
    "export", "default", "case", "switch", "break", "continue", "pass",
}

MIN_LINES = 3
MIN_OCCURRENCES = 2


def _text(value):
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


def added_blocks(diff_text):
    """Contiguous runs of added lines, as [{file, start, lines[]}, ...].

    A run is broken by a context line, a removal, a hunk header or a new file —
    so each block is one coherent insertion, not the whole file's additions.
    """
    diff_text = _text(diff_text)
    if not diff_text.strip():
        return []
    try:
        blocks, current, current_file, lineno = [], None, "", 0

        def flush():
            nonlocal current
            if current and current["lines"]:
                blocks.append(current)
            current = None

        for raw in diff_text.splitlines():
            m = DIFF_GIT.match(raw)
            if m:
                flush()
                current_file = m.group(2).strip()
                lineno = 0
                continue
            if HUNK.match(raw) or raw.startswith(("+++", "---", "index ", "new file", "deleted file")):
                flush()
                continue
            if raw.startswith("+"):
                lineno += 1
                body = raw[1:]
                if current is None:
                    current = {"file": current_file, "start": lineno, "lines": []}
                current["lines"].append(body)
            else:
                flush()
                lineno += 1
        flush()
        return blocks
    except Exception:
        return []


def definitions(diff_text):
    """Functions and classes introduced by a diff's added lines."""
    out = []
    for block in added_blocks(diff_text):
        for offset, line in enumerate(block["lines"]):
            for rx, kind in ((PY_CLASS, "class"), (JS_CLASS, "class")):
                m = rx.match(line)
                if m:
                    out.append({"name": m.group(1), "kind": kind, "params": "",
                                "file": block["file"], "line": block["start"] + offset})
                    break
            else:
                m = PY_DEF.match(line)
                if m:
                    out.append({"name": m.group(1), "kind": "function", "params": m.group(2).strip(),
                                "file": block["file"], "line": block["start"] + offset})
                    continue
                m = JS_DEF.match(line)
                if m:
                    name = m.group(1) or m.group(3)
                    params = (m.group(2) or m.group(4) or "").strip()
                    if name:
                        out.append({"name": name, "kind": "function", "params": params,
                                    "file": block["file"], "line": block["start"] + offset})
    # de-duplicate on (name, file, line)
    seen, uniq = set(), []
    for d in out:
        key = (d["name"], d["file"], d["line"])
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq


def normalize(lines):
    """Structural fingerprint of a code block.

    Identifiers → `N`, literals → `L`, indentation preserved as depth, so two
    copy-pasted-and-renamed blocks share a fingerprint.
    """
    if isinstance(lines, str):
        lines = lines.splitlines()
    out = []
    for raw in lines or []:
        line = _text(raw)
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        depth = (len(line) - len(line.lstrip())) // 2
        text = STRING.sub("L", line.strip())
        text = NUMBER.sub("L", text)
        text = IDENT.sub(lambda m: m.group(0) if m.group(0).lower() in KEYWORDS else "N", text)
        text = re.sub(r"\s+", " ", text).strip()
        out.append(f"{depth}|{text}")
    return "\n".join(out)


def fingerprint(lines):
    """Stable short hash of `normalize(lines)`. Empty string when nothing is left."""
    norm = normalize(lines)
    if not norm:
        return ""
    return hashlib.sha1(norm.encode()).hexdigest()[:12]


BOILERPLATE_LINE = re.compile(
    r"^\s*(?:import\s|from\s+\S+\s+import\b|@|export\s+\{|\"\"\"|'''|\}|\)|\]|else:?$|try:?$)"
)


def is_boilerplate(lines):
    """True when a block is only imports, decorators, docstrings or closers.

    Repeated import headers and field declarations are a project *convention*,
    not an extractable helper; reporting them buries the real candidates.
    """
    meaningful = 0
    for raw in lines or []:
        line = _text(raw).strip()
        if not line or line.startswith(("#", "//")):
            continue
        if BOILERPLATE_LINE.match(_text(raw)):
            continue
        # Bare `name: type` / `name: type = default` field declarations.
        if re.match(r"^[A-Za-z_][\w]*\s*:\s*[^=]+(?:=.*)?$", line) and "(" not in line:
            continue
        meaningful += 1
    return meaningful < 2


def find_duplicates(diff_text, min_lines=MIN_LINES, min_occurrences=MIN_OCCURRENCES):
    """Group added blocks that share a structural fingerprint.

    Returns [{fingerprint, occurrences, files, sites, identical_text, sample}].
    """
    groups, seen_sites = {}, set()
    for block in added_blocks(diff_text):
        # The same block seen again at the same file:line is one site observed
        # twice (cherry-pick, merge, a multi-commit stream), not duplication.
        site = (block["file"], block["start"])
        if site in seen_sites:
            continue
        seen_sites.add(site)
        body = [ln for ln in block["lines"] if ln.strip()]
        if len(body) < max(1, int(min_lines or 1)):
            continue
        if is_boilerplate(body):
            continue
        fp = fingerprint(body)
        if not fp:
            continue
        groups.setdefault(fp, []).append(block)
    out = []
    for fp, blocks in groups.items():
        if len(blocks) < max(2, int(min_occurrences or 2)):
            continue
        texts = {"\n".join(b["lines"]).strip() for b in blocks}
        out.append({
            "fingerprint": fp,
            "occurrences": len(blocks),
            "files": sorted({b["file"] for b in blocks}),
            "sites": [f"{b['file']}:{b['start']}" for b in blocks],
            "identical_text": len(texts) == 1,
            "sample": blocks[0]["lines"][:12],
        })
    out.sort(key=lambda g: (-g["occurrences"], g["fingerprint"]))
    return out


def _suggest_name(sample, index):
    """Pick a helper name from the block's most distinctive keyword-adjacent word."""
    words = []
    for line in sample or []:
        for w in IDENT.findall(_text(line)):
            lw = w.lower()
            if lw not in KEYWORDS and len(w) > 3:
                words.append(re.sub(r"[^a-z0-9]+", "_", lw))
    if not words:
        return f"shared_helper_{index + 1}"
    # most frequent, tie-broken by first appearance
    best = max(set(words), key=lambda w: (words.count(w), -words.index(w)))
    return f"{best}_helper"


def propose_abstractions(diff_text, min_lines=MIN_LINES, min_occurrences=MIN_OCCURRENCES):
    """Reusable-helper candidates found in a diff, highest confidence first.

    Each proposal carries `rationale` explaining *why* the block is a candidate,
    so the document a caller renders is auditable rather than assertive.
    """
    try:
        dups = find_duplicates(diff_text, min_lines, min_occurrences)
        defined = {d["name"] for d in definitions(diff_text)}
        proposals = []
        for i, g in enumerate(dups):
            cross_file = len(g["files"]) > 1
            confidence = "high" if cross_file and not g["identical_text"] else (
                "high" if cross_file else "medium")
            rationale = [
                f"the same {len(g['sample'])}-line structure is added {g['occurrences']} times",
                "across " + (f"{len(g['files'])} files" if cross_file else "one file"),
            ]
            if g["identical_text"]:
                rationale.append("the occurrences are byte-identical — a literal copy-paste")
            else:
                rationale.append("the occurrences differ only in identifiers/literals — "
                                 "a copy-paste-and-rename, which text search will not find")
            name = _suggest_name(g["sample"], i)
            while name in defined:
                name = "_" + name
            proposals.append({
                "name": name,
                "kind": "function",
                "fingerprint": g["fingerprint"],
                "occurrences": g["occurrences"],
                "files": g["files"],
                "sites": g["sites"],
                "confidence": confidence,
                "rationale": rationale,
                "sample": g["sample"],
                "saves_lines": max(0, (g["occurrences"] - 1) * len(g["sample"])),
            })
        return proposals
    except Exception:
        return []


def render_document(proposals, title="Identified abstractions"):
    """Render proposals as a markdown document. Returns "" when there is nothing to say."""
    proposals = [p for p in (proposals or []) if isinstance(p, dict)]
    if not proposals:
        return ""
    lines = [f"# {title}", "",
             f"{len(proposals)} candidate abstraction(s), ordered by number of occurrences.",
             "Each entry states what repeats, where, and why it is worth extracting.", ""]
    for p in proposals:
        lines.append(f"## `{p['name']}` — {p['occurrences']}× ({p['confidence']} confidence)")
        lines.append("")
        lines.append(f"**Sites:** {', '.join(p['sites'][:6])}")
        lines.append(f"**Removes:** ~{p['saves_lines']} duplicated line(s)")
        lines.append("")
        lines.append("**Rationale:** " + "; ".join(p["rationale"]) + ".")
        lines.append("")
        lines.append("```")
        lines.extend(p["sample"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def analyze(diff_text, title="Identified abstractions"):
    """One-call entry point: {definitions, duplicates, proposals, document}."""
    return {
        "definitions": definitions(diff_text),
        "duplicates": find_duplicates(diff_text),
        "proposals": propose_abstractions(diff_text),
        "document": render_document(propose_abstractions(diff_text), title),
    }


if __name__ == "__main__":
    result = analyze(sys.stdin.read())
    print(result["document"] or "no abstraction candidates found")
