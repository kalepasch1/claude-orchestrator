#!/usr/bin/env python3
"""Public-copy disclosure guard.

Scans newly added public-facing page/component/content text before release.
The policy is intentionally about mechanism disclosure, not marketing value:
general claims such as "privacy-preserving" or "compliance-aware" are fine;
specific model-routing, IP-partitioning, or legal/regulatory playbooks are not.
"""
import os
import re
import subprocess


PUBLIC_EXTS = {
    ".astro", ".html", ".jsx", ".json", ".md", ".mdx", ".svelte",
    ".tsx", ".vue",
}
PUBLIC_PATH_RE = re.compile(
    r"(^|/)(app|assets/copy|components|content|i18n|layouts|locales|marketing|"
    r"messages|pages|public|src/app|src/components|src/content|src/layouts|src/pages)(/|$)"
)
IGNORED_LINE_RE = re.compile(
    r"^\s*(import\b|export\s+(type|interface)\b|type\s+\w+\s*=|interface\s+\w+\b|"
    r"//|/\*|\*|<!--|</?(script|style)\b)",
    re.I,
)


RULES = [
    (
        "proprietary_mechanism",
        re.compile(
            r"\b(CADE|common brain|agent market|agent mesh|hivemind|model slashing|"
            r"prompt bankruptcy|outcome-based prompt bankruptcy|verifier marketplace|"
            r"merged[- ]diff library|patch transplant|thermal map|EV/min|"
            r"sub[- ]subtask slicing|local[- ]only routing|crown[- ]jewel routing|"
            r"provider[- ]term metadata|no[- ]training provider|tokens avoided|"
            r"minutes avoided|brain compiler)\b",
            re.I,
        ),
        "Use value-level language; do not name or describe proprietary orchestration mechanisms.",
    ),
    (
        "legal_strategy",
        re.compile(
            r"\b(legal strategy|regulatory strategy|regulatory arbitrage|UPL|"
            r"unauthorized practice|privilege guard|attorney[- ]client privilege|"
            r"work[- ]product strategy|avoid(?:s|ing)?\s+(?:CFTC|SEC|money transmission|"
            r"broker[- ]dealer|investment adviser|DCM|SEF|legal advice|custody)|"
            # A DISCLAIMER IS NOT A PLAYBOOK.
            #
            # "not legal advice" used to be in this alternation, and it blocked nine
            # apparently-law releases on 2026-09-02:
            #
            #   [gate:copy] public-copy disclosure gate red — self-heal queued:
            #   - app/pages/for/ai-data.vue:21 [legal_strategy]:
            #     Informational only not legal advice.
            #
            # The line it flagged is the bar-required attorney-advertising disclaimer:
            # "Attorney advertising. Informational only, not legal advice. No
            # attorney-client relationship is formed by using this site." It appears in
            # at least eight places across that site, every one of them mandatory.
            #
            # The distinction this rule is for: a STRATEGY says how the company avoids a
            # regulator, which `avoid(s|ing) ... legal advice` above still catches. A
            # DISCLAIMER says what the product is not, to protect the reader -- the
            # opposite of a disclosure risk, and in this case a legal obligation.
            #
            # "not custody", "not money transmission", "not securities" and "not a
            # broker-dealer" USED to be here too. Operator decision 2026-09-02: they are
            # the same shape as the attorney-advertising disclaimer above -- standard
            # disclaimers a fintech page is expected to carry -- so they no longer block
            # a release. They are not simply dropped: see DISCLAIMER_RULES below, which
            # reports them without failing the gate.
            r"work[- ]product playbook)\b",
            re.I,
        ),
        "Describe compliance value generally; do not publish the legal/regulatory playbook.",
    ),
    (
        "vendor_ip_partitioning",
        re.compile(
            r"\b(no\s+(?:single\s+)?(?:model|vendor)\s+(?:sees|learns|gets)\s+"
            r"(?:the\s+)?(?:full\s+)?(?:IP|strategy|app)|"
            r"split(?:ting)?\s+.{0,80}\s+across\s+.{0,80}\s+models\s+.{0,80}"
            r"(?:IP|strategy|secret)|vendors?\s+(?:.{0,80}\s+)?cannot\s+.{0,80}replicate|"
            r"(?:Claude|GPT|OpenAI|Anthropic|Gemini|Google|DeepSeek|Ollama)\s+"
            r".{0,80}(?:learn|retain|replicate)\s+.{0,80}(?:IP|code|strategy))\b",
            re.I,
        ),
        "Keep AI-vendor/IP protection claims abstract; do not disclose partitioning tactics.",
    ),
    (
        "specific_vendor_routing",
        re.compile(
            r"\b(?:route|routing|triage|triaging)\s+.{0,80}\b"
            r"(?:Claude|GPT|OpenAI|Anthropic|Gemini|Google|DeepSeek|Ollama)\b"
            r".{0,80}\b(?:cost|capability|vendor|model|fallback|local)\b",
            re.I,
        ),
        "Do not expose internal vendor/model routing logic in public UI copy.",
    ),
]


def _git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


#: Reported, never blocking. These are the phrases an operator wants to KNOW about
#: rather than be stopped by.
#:
#: Operator decision 2026-09-02, after the attorney-advertising disclaimer
#: ("Informational only, not legal advice") failed nine apparently-law releases: the
#: regulatory equivalents are the same shape. "not custody", "not money transmission",
#: "not securities", "not a broker-dealer" are disclaimers a fintech page is expected to
#: carry -- they say what the product is NOT, to protect the reader, which is the
#: opposite of disclosing a playbook. Genuine strategy phrasing is still caught by the
#: `avoid(s|ing) ...` branch in legal_strategy, which is unchanged and still blocks.
#:
#: So: the release ships, and a coordination task names the page. The operator sees it
#: without a failed release.
DISCLAIMER_RULES = [
    (
        "regulatory_disclaimer",
        re.compile(
            r"\bnot\s+(?:a\s+)?(?:custody|money transmission|money transmitter|"
            r"securities|broker[- ]dealer|investment advice)\b",
            re.I,
        ),
        "Regulatory disclaimer published. Allowed; confirm it is the wording you want.",
    ),
]


def _is_public_file(path):
    ext = os.path.splitext(str(path or ""))[1].lower()
    return ext in PUBLIC_EXTS and bool(PUBLIC_PATH_RE.search(str(path or "")))


_BLOCK_OPENERS = (("<!--", "-->"), ("/*", "*/"))


def _block_comment_mask(lines):
    """Which of `lines` sit inside a multi-line comment. Returns a list of bool.

    IGNORED_LINE_RE only recognises a comment by how a line STARTS (`//`, `/*`,
    `*`, `<!--`). The MIDDLE lines of a block comment start with ordinary prose,
    so the guard read them as display copy.

    That is what blocked apparently release ce3433f9: line 5 of
    app/components/one-apparently/BenchReviewedSeal.vue is the middle of an HTML
    comment reading "...the internal engine id (CADE) never surfaces here" — a
    comment whose entire purpose is to state the very rule this guard enforces.
    The gate flagged the documentation of its own rule and stopped a release.

    State is tracked only across the lines actually supplied. The caller passes
    added diff lines, so an opener outside that window is invisible and those
    lines stay scanned — deliberately fail-open toward MORE scanning, never less.
    """
    mask, closer = [], None
    for raw in lines:
        text = str(raw or "")
        if closer:
            mask.append(True)
            if closer in text:
                closer = None
            continue
        opened = None
        for start, end in _BLOCK_OPENERS:
            i = text.find(start)
            if i >= 0 and end not in text[i + len(start):]:
                opened = end
                break
        mask.append(False)
        closer = opened
    return mask


def _is_block_comment_body(raw):
    """True when `raw` alone opens an unterminated block comment."""
    return bool(_block_comment_mask([raw, ""])[1])


def _looks_displayish(raw):
    text = (raw or "").strip()
    if not text:
        return False
    if IGNORED_LINE_RE.search(text):
        return False
    # Ignore obvious code-only structural lines, but keep quoted/HTML/JSX text.
    if not any(ch.isalpha() for ch in text):
        return False
    if re.match(r"^[{}\[\](),.;:]+$", text):
        return False
    return True


def _clean(raw):
    text = str(raw or "")
    text = re.sub(r"\b(class(Name)?|style|href|src|to|key|id)=['\"][^'\"]*['\"]", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[`\"'{}()[\]=,:;]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def scan_lines(path, lines, rules=None):
    """Scan added lines for one public-facing file.

    `rules` defaults to the blocking RULES. Pass DISCLAIMER_RULES for the advisory
    pass -- same masking, same cleaning, same excerpting, so an advisory finding is
    exactly as trustworthy as a blocking one.
    """
    if not _is_public_file(path):
        return []
    rules = RULES if rules is None else rules
    findings = []
    lines = list(lines)
    # A block comment's middle lines start with prose, so they must be masked
    # by position, not by how the individual line begins (see _block_comment_mask).
    in_comment = _block_comment_mask([raw for _, raw in lines])
    for index, (line_no, raw) in enumerate(lines):
        if in_comment[index]:
            continue
        if not _looks_displayish(raw):
            continue
        text = _clean(raw)
        if not text:
            continue
        haystack = f"{raw}\n{text}"
        for rule, pattern, guidance in rules:
            if pattern.search(haystack):
                findings.append({
                    "file": path,
                    "line": line_no,
                    "rule": rule,
                    "excerpt": text[:220],
                    "guidance": guidance,
                })
                break
    return findings


def _added_lines_by_file(diff_text):
    current = None
    new_line = 0
    lines = {}
    for raw in (diff_text or "").splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:]
            new_line = 0
            continue
        if raw.startswith("+++ /dev/null"):
            current = None
            continue
        hunk = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if current is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            lines.setdefault(current, []).append((new_line, raw[1:]))
            new_line += 1
        elif not raw.startswith("-"):
            new_line += 1
    return lines


def scan_diff(repo, base_ref, head_ref, project=None):
    """Return a release-gate result for public UI copy changes."""
    if os.environ.get("ORCH_PUBLIC_COPY_GATE", "true").lower() not in ("1", "true", "yes", "on"):
        return {"pass": True, "findings": [], "notes": "public copy gate disabled"}
    if not repo or not os.path.isdir(repo):
        return {"pass": True, "findings": [], "notes": "repo missing; skipped"}
    r = _git(repo, "diff", "--unified=0", "--diff-filter=ACMR", f"{base_ref}..{head_ref}", timeout=120)
    if r.returncode != 0:
        return {"pass": False, "findings": [{
            "file": "(git diff)",
            "line": 0,
            "rule": "scan_error",
            "excerpt": (r.stderr or r.stdout or "git diff failed")[-220:],
            "guidance": "Public-copy guard could not inspect the staged release diff.",
        }], "notes": "scan failed"}
    findings, advisories = [], []
    for path, added in _added_lines_by_file(r.stdout).items():
        findings.extend(scan_lines(path, added))
        advisories.extend(scan_lines(path, added, rules=DISCLAIMER_RULES))
    max_findings = int(os.environ.get("ORCH_PUBLIC_COPY_MAX_FINDINGS", "25") or 25)
    findings = findings[:max_findings]
    advisories = advisories[:max_findings]
    if advisories:
        _alert_disclaimers(project, advisories)
    notes = "ok" if not findings else f"{len(findings)} public-copy disclosure finding(s)"
    if advisories:
        notes += f" ({len(advisories)} regulatory disclaimer(s) reported, not blocking)"
    return {
        # `pass` depends on the BLOCKING findings only. An advisory that failed the gate
        # would be a blocking rule wearing a different name.
        "pass": not findings,
        "findings": findings,
        "advisories": advisories,
        "notes": notes,
        "project": project or "",
    }


def _alert_disclaimers(project, advisories):
    """File ONE coordination task naming the pages. Never raises, never floods.

    Deduped on a signature of (project, file:line set) within ALERT_DEDUPE_HOURS, for
    the reason done_to_merged learned the hard way: a row per pass is not a record, it
    is a metronome.
    """
    try:
        import hashlib
        import json as _json
        import time as _time
        import db
        where = sorted({"%s:%s" % (a.get("file"), a.get("line")) for a in advisories})
        sig = hashlib.sha256(("%s|%s" % (project or "", "|".join(where))).encode()).hexdigest()[:16]
        hours = float(os.environ.get("ORCH_COPY_ALERT_DEDUPE_HOURS", "24") or 24)
        since = _time.strftime("%Y-%m-%dT%H:%M:%SZ",
                               _time.gmtime(_time.time() - hours * 3600.0))
        try:
            seen = db.select("coordination_tasks", {
                "select": "id,payload", "task_type": "eq.public_copy_disclaimer",
                "created_at": f"gte.{since}", "limit": "200"}) or []
        except Exception:
            seen = []
        if any(sig in str(row.get("payload") or "") for row in seen):
            return False
        db.insert("coordination_tasks", {
            "task_type": "public_copy_disclaimer",
            "payload": _json.dumps({
                "at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                "signature": sig,
                "project": project or "",
                "note": ("Regulatory disclaimer wording published. This did NOT block the "
                         "release; it is here so the wording is seen. Operator decision "
                         "2026-09-02."),
                "pages": where,
                "excerpts": [str(a.get("excerpt"))[:200] for a in advisories[:8]],
            })[:8000]}, upsert=False)
        print("public_copy_guard: %d regulatory disclaimer(s) reported for %s (%s) — "
              "release not blocked" % (len(advisories), project or "?", ", ".join(where[:3])),
              flush=True)
        return True
    except Exception:
        return False


def format_findings(findings):
    out = []
    for f in findings or []:
        loc = f"{f.get('file')}:{f.get('line')}"
        out.append(f"- {loc} [{f.get('rule')}]: {f.get('excerpt')}\n  Fix: {f.get('guidance')}")
    return "\n".join(out)


if __name__ == "__main__":
    import json
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    base = sys.argv[2] if len(sys.argv) > 2 else "HEAD~1"
    head = sys.argv[3] if len(sys.argv) > 3 else "HEAD"
    print(json.dumps(scan_diff(repo, base, head), indent=2))
