#!/usr/bin/env python3
"""
artifact_catalog.py — zero-spend scavenger that turns leftover build artifacts
back into candidate source modifications.

When an agent branch goes missing, the machine that ran it usually still holds
enough debris to reconstruct the patch: build logs that echoed a diff, `.patch`
files, `.rej` rejects from a failed `patch -p1`, `.orig`/`.new` backups, and
object files carrying source paths in their debug strings.

`build_catalog(root)` walks that debris and returns a mapping

    { "<source/path>": [ {artifact, kind, content}, ... ] }

so `jq 'keys' catalog.json` answers "which files do the artifacts claim were
modified?" — the question `patch_recovery.py` asks before it spends a token.

Evidence discipline (this is why the acceptance test has no false positives):
a path becomes a key ONLY when an artifact carries an explicit *modification*
marker for it — a diff hunk, a reject, a backup pair, or a change verb in a log.
A path merely *mentioned* in a log or embedded in a binary is not evidence that
it changed, so by default those only enrich keys that other evidence created.
"""
import argparse
import json
import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
             ".pytest_cache", "dist", ".next", ".nuxt"}

PATCH_EXT = (".patch", ".diff")
BINARY_EXT = (".o", ".obj", ".a", ".so", ".dylib", ".pyc", ".class")
LOG_EXT = (".log", ".txt", ".out", ".err", ".jsonl")

SOURCE_EXT = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".mjs", ".cjs", ".go", ".rs",
    ".java", ".rb", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".php", ".swift",
    ".kt", ".scala", ".sh", ".sql", ".css", ".scss", ".json", ".yaml", ".yml",
    ".toml", ".md", ".prisma", ".graphql",
)

MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_BINARY_BYTES = 32 * 1024 * 1024

_DIFF_GIT_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)\s*$")
_PLUS_RE = re.compile(r"^\+\+\+ (?:b/)?(\S+)")
_MINUS_RE = re.compile(r"^--- (?:a/)?(\S+)")

# Explicit "this file changed" verbs. Anything not on this list is not evidence.
_LOG_MARKERS = (
    re.compile(r"^\s*modified:\s+(\S+)\s*$"),
    re.compile(r"^\s*new file:\s+(\S+)\s*$"),
    re.compile(r"^\s*deleted:\s+(\S+)\s*$"),
    re.compile(r"^\s*(?:patching file|checking file)\s+(\S+)\s*$"),
    re.compile(r"^\s*(?:Wrote|Writing|Updated|Rewrote|Created)\s+(\S+)\s*$"),
    re.compile(r"^\s*CHANGED:\s*(\S+)\s*$"),
    # `git status --short` / `git diff --name-status`
    re.compile(r"^\s{0,2}[MAD]\s{1,2}(\S+)\s*$"),
    re.compile(r"^[MAD]\t(\S+)\s*$"),
)

_BIN_STRING_RE = re.compile(rb"[\x20-\x7e]{6,}")


def normalize_path(raw):
    """Strip diff prefixes and leading ./ so every extractor keys the same way."""
    if not raw:
        return None
    p = raw.strip().strip('"').strip("'")
    if p.startswith(("a/", "b/", "i/", "w/", "c/", "o/")):
        p = p[2:]
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    return p or None


def looks_like_source_path(p):
    """Conservative plausibility gate — keeps prose out of the catalog."""
    if not p or len(p) < 3 or " " in p:
        return False
    if p in ("dev/null", "/dev/null") or p.endswith("/"):
        return False
    if "://" in p or p.startswith("-"):
        return False
    return p.lower().endswith(SOURCE_EXT)


def parse_unified_diff(text):
    """Yield (path, hunk_text) for every hunk in a unified diff.

    Tolerates diffs embedded in build-log noise: a hunk ends as soon as a line
    appears that cannot belong to it, and a file context is only trusted from a
    `diff --git` or `+++` header.
    """
    out = []
    current = None
    hunk = None

    def _flush():
        nonlocal hunk
        if current and hunk:
            out.append((current, "\n".join(hunk)))
        hunk = None

    for line in text.splitlines():
        m = _DIFF_GIT_RE.match(line)
        if m:
            _flush()
            current = normalize_path(m.group(2))
            continue
        m = _PLUS_RE.match(line)
        if m:
            _flush()
            target = normalize_path(m.group(1))
            if target in ("dev/null", None):
                # deletion — fall back to the pre-image path so the file is still catalogued
                current = current
            else:
                current = target
            continue
        if _MINUS_RE.match(line):
            if current is None:
                current = normalize_path(_MINUS_RE.match(line).group(1))
            continue
        if line.startswith("@@"):
            _flush()
            hunk = [line]
            continue
        if hunk is not None:
            if line == "" or line[0] in " +-\\":
                hunk.append(line)
            else:
                _flush()
    _flush()
    return [(p, h) for p, h in out if looks_like_source_path(p)]


def parse_change_markers(text):
    """Return paths a log explicitly claims were changed (not merely mentioned)."""
    found = []
    for line in text.splitlines():
        for rx in _LOG_MARKERS:
            m = rx.match(line)
            if not m:
                continue
            p = normalize_path(m.group(1))
            if looks_like_source_path(p):
                found.append((p, line.strip()))
            break
    return found


def extract_binary_paths(data):
    """Source-looking paths embedded in an object file's debug strings."""
    seen = []
    for chunk in _BIN_STRING_RE.findall(data):
        try:
            s = chunk.decode("ascii")
        except UnicodeDecodeError:
            continue
        for token in re.split(r"[\s\x00,;:()\[\]{}<>\"']+", s):
            p = normalize_path(token)
            if looks_like_source_path(p) and "/" in p and p not in seen:
                seen.append(p)
    return seen


def _read_text(path, limit=MAX_TEXT_BYTES):
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _read_bytes(path, limit=MAX_BINARY_BYTES):
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def iter_artifact_files(root):
    """Walk `root` yielding absolute paths, skipping vendored/VCS noise."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def classify_artifact(path):
    low = os.path.basename(path).lower()
    if low.endswith(PATCH_EXT):
        return "patch"
    if low.endswith(".rej"):
        return "reject"
    if low.endswith(".orig"):
        return "orig"
    if low.endswith(".new"):
        return "new"
    if low.endswith(BINARY_EXT):
        return "binary"
    if low.endswith(LOG_EXT) or low.endswith(".md"):
        return "log"
    return None


def _add(catalog, path, artifact, kind, content, root):
    if not looks_like_source_path(path):
        return
    rel_artifact = os.path.relpath(artifact, root)
    entry = {"artifact": rel_artifact, "kind": kind, "content": content}
    bucket = catalog.setdefault(path, [])
    if entry not in bucket:
        bucket.append(entry)


def _target_from_suffix(path, root, suffix):
    """`<root>/runner/foo.py.orig` -> `runner/foo.py`."""
    rel = os.path.relpath(path, root)
    return normalize_path(rel[: -len(suffix)])


def build_catalog(root, include_binary=False):
    """Scan `root` and return {source_path: [candidate, ...]}.

    Only artifacts carrying explicit modification evidence create keys. Binary
    debug strings enrich existing keys, and create new ones only when the caller
    opts in with `include_binary` (they prove compilation, not modification).
    """
    root = os.path.abspath(root)
    catalog = {}
    binary_hits = []

    for path in iter_artifact_files(root):
        kind = classify_artifact(path)
        if kind is None:
            continue

        if kind == "binary":
            data = _read_bytes(path)
            if data:
                for p in extract_binary_paths(data):
                    binary_hits.append((p, path))
            continue

        text = _read_text(path)
        if text is None:
            continue

        if kind in ("patch", "reject", "log"):
            hunks = parse_unified_diff(text)
            for p, hunk in hunks:
                _add(catalog, p, path, "reject_hunk" if kind == "reject" else "patch_hunk",
                     hunk, root)
            if kind == "reject" and not hunks:
                target = _target_from_suffix(path, root, ".rej")
                _add(catalog, target, path, "reject_hunk", text, root)
            if kind == "log":
                for p, line in parse_change_markers(text):
                    _add(catalog, p, path, "log_change_marker", line, root)

        elif kind == "new":
            target = _target_from_suffix(path, root, ".new")
            _add(catalog, target, path, "new_content", text, root)

        elif kind == "orig":
            target = _target_from_suffix(path, root, ".orig")
            sibling = path[: -len(".orig")]
            post = _read_text(sibling)
            if post is not None:
                _add(catalog, target, sibling, "post_patch_content", post, root)
            else:
                _add(catalog, target, path, "pre_patch_content", text, root)

    for p, artifact in binary_hits:
        if include_binary or p in catalog:
            _add(catalog, p, artifact, "binary_debug_string", p, root)

    return {k: catalog[k] for k in sorted(catalog)}


def to_plain_strings(catalog):
    """Collapse each entry to its bare candidate content."""
    return {k: [e["content"] for e in v] for k, v in catalog.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Catalog candidate source modifications found in build artifacts."
    )
    ap.add_argument("--root", default=".", help="artifacts directory (default: cwd)")
    ap.add_argument("--out", default="catalog.json", help="output path (- for stdout)")
    ap.add_argument("--include-binary", action="store_true",
                    help="let object-file debug strings create keys (weaker evidence)")
    ap.add_argument("--strings", action="store_true",
                    help="emit bare candidate strings instead of {artifact,kind,content}")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.root):
        print(f"artifact_catalog: not a directory: {args.root}", file=sys.stderr)
        return 2

    catalog = build_catalog(args.root, include_binary=args.include_binary)
    payload = to_plain_strings(catalog) if args.strings else catalog
    blob = json.dumps(payload, indent=2, sort_keys=True)

    if args.out == "-":
        print(blob)
    else:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(blob + "\n")
        print(f"artifact_catalog: {len(catalog)} file(s) -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
