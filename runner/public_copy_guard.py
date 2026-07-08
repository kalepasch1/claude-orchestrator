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
            r"not\s+(?:custody|money transmission|legal advice|securities|broker[- ]dealer))\b",
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


def _is_public_file(path):
    ext = os.path.splitext(str(path or ""))[1].lower()
    return ext in PUBLIC_EXTS and bool(PUBLIC_PATH_RE.search(str(path or "")))


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


def scan_lines(path, lines):
    """Scan added lines for one public-facing file."""
    if not _is_public_file(path):
        return []
    findings = []
    for line_no, raw in lines:
        if not _looks_displayish(raw):
            continue
        text = _clean(raw)
        if not text:
            continue
        haystack = f"{raw}\n{text}"
        for rule, pattern, guidance in RULES:
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
    findings = []
    for path, added in _added_lines_by_file(r.stdout).items():
        findings.extend(scan_lines(path, added))
    max_findings = int(os.environ.get("ORCH_PUBLIC_COPY_MAX_FINDINGS", "25") or 25)
    findings = findings[:max_findings]
    return {
        "pass": not findings,
        "findings": findings,
        "notes": "ok" if not findings else f"{len(findings)} public-copy disclosure finding(s)",
        "project": project or "",
    }


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
