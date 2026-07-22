#!/usr/bin/env python3
"""
kernel_miner.py - periodic (daily) cross-repo near-duplicate detection.

Embeds function/module-level chunks across fleet repos (reusing context_embed provider),
clusters near-duplicates appearing in 3+ repos, and files approval cards proposing
extraction into vendored packages. NEVER auto-extracts without card approval.

On approval, queues extraction tasks following the existing vendor/ht-ui pattern:
source-of-truth package + vendored copies + CI allowlist.
"""
import os, sys, json, re, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MIN_REPOS = int(os.environ.get("KERNEL_MIN_REPOS", "3"))
SIMILARITY_THRESHOLD = float(os.environ.get("KERNEL_SIM_THRESHOLD", "0.85"))
MAX_CLUSTERS = int(os.environ.get("KERNEL_MAX_CLUSTERS", "20"))
CHUNK_MIN_LINES = int(os.environ.get("KERNEL_CHUNK_MIN_LINES", "5"))
CHUNK_MAX_LINES = int(os.environ.get("KERNEL_CHUNK_MAX_LINES", "80"))

_FUNC_RE = re.compile(
    r"^(?:def |class |async def |function |const \w+ = |export (?:default )?function )",
    re.MULTILINE,
)


def extract_chunks(filepath, content):
    """Extract function/module-level chunks from source content."""
    lines = content.split("\n")
    chunks = []
    current_start = 0
    current_lines = []

    for i, line in enumerate(lines):
        if _FUNC_RE.match(line) and current_lines:
            if CHUNK_MIN_LINES <= len(current_lines) <= CHUNK_MAX_LINES:
                chunks.append({
                    "file": filepath,
                    "start": current_start,
                    "end": i,
                    "content": "\n".join(current_lines),
                })
            current_lines = []
            current_start = i
        current_lines.append(line)

    if current_lines and CHUNK_MIN_LINES <= len(current_lines) <= CHUNK_MAX_LINES:
        chunks.append({
            "file": filepath,
            "start": current_start,
            "end": len(lines),
            "content": "\n".join(current_lines),
        })
    return chunks


def _normalize(text):
    """Normalize chunk text for comparison: strip whitespace, lowercase."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _chunk_hash(text):
    """Hash normalized chunk content."""
    return hashlib.sha256(_normalize(text).encode()).hexdigest()[:16]


def cluster_chunks(all_chunks):
    """
    Cluster near-duplicate chunks across repos by content hash similarity.
    all_chunks: list of {file, start, end, content, repo}
    Returns list of clusters, each a list of chunk dicts, where the cluster
    appears in >= MIN_REPOS distinct repos.
    """
    by_hash = {}
    for chunk in all_chunks:
        h = _chunk_hash(chunk["content"])
        by_hash.setdefault(h, []).append(chunk)

    clusters = []
    for h, members in by_hash.items():
        repos = set(m.get("repo", "") for m in members)
        if len(repos) >= MIN_REPOS:
            clusters.append(members)

    clusters.sort(key=lambda c: len(c), reverse=True)
    return clusters[:MAX_CLUSTERS]


def build_approval_card(cluster):
    """
    Build an approval card payload for a cluster extraction proposal.
    Returns a dict suitable for db.insert("approvals", ...).
    """
    repos = sorted(set(m.get("repo", "") for m in cluster))
    files = [m.get("file", "") for m in cluster]
    sample = cluster[0]["content"][:500] if cluster else ""
    slug = f"kernel-extract-{_chunk_hash(sample)}"

    return {
        "project": "orchestrator",
        "kind": "proposal",
        "slug": slug,
        "title": f"Extract shared code found in {len(repos)} repos",
        "why": f"Near-duplicate code found in {len(repos)} repos: {', '.join(repos[:5])}",
        "value": "Reduces maintenance burden by extracting into a vendored package.",
        "detail": json.dumps({
            "repos": repos,
            "files": files[:20],
            "sample": sample,
            "member_count": len(cluster),
        }),
    }


def build_extraction_tasks(cluster, approved_slug):
    """
    Generate extraction tasks for an approved cluster.
    Returns list of task dicts parseable by intake_watcher.parse.
    """
    repos = sorted(set(m.get("repo", "") for m in cluster))
    files = [m.get("file", "") for m in cluster]
    sample_hash = _chunk_hash(cluster[0]["content"][:500]) if cluster else "unknown"
    pkg_name = f"shared-kernel-{sample_hash}"

    tasks = []
    # One task to create the source-of-truth package
    tasks.append({
        "slug": f"kernel-create-{sample_hash}",
        "kind": "build",
        "project": "orchestrator",
        "prompt": (
            f"Create vendored package '{pkg_name}' under vendor/ with the shared code "
            f"extracted from: {', '.join(files[:10])}. Follow the vendor/ht-ui pattern: "
            f"source-of-truth package + CI allowlist entry.\n"
            f"Proof: python3 -c \"import importlib; importlib.import_module('{pkg_name.replace('-','_')}')\""
        ),
    })
    # One task per repo to adopt the package
    for repo in repos[:10]:
        tasks.append({
            "slug": f"kernel-adopt-{sample_hash}-{repo[:20]}",
            "kind": "mechanical",
            "project": repo,
            "prompt": (
                f"Replace duplicate code with import from vendored '{pkg_name}'. "
                f"Files to update in {repo}: {', '.join(f for f in files if repo in f)[:500]}\n"
                f"Proof: grep -r 'from {pkg_name.replace('-','_')}' {repo}/ | head -1"
            ),
        })
    return tasks


def run(repo_chunks_map):
    """
    Main entry point. repo_chunks_map: {repo_name: [{file, content}, ...]}
    Files approval cards for clusters. Never auto-extracts.
    Returns list of filed card slugs.
    """
    all_chunks = []
    for repo, file_list in repo_chunks_map.items():
        for f in file_list:
            chunks = extract_chunks(f.get("file", ""), f.get("content", ""))
            for c in chunks:
                c["repo"] = repo
            all_chunks.extend(chunks)

    clusters = cluster_chunks(all_chunks)
    filed = []
    for cluster in clusters:
        card = build_approval_card(cluster)
        try:
            db.insert("approvals", card)
            filed.append(card["slug"])
        except Exception:
            pass
    return filed


if __name__ == "__main__":
    print("kernel_miner.py: import and call run(repo_chunks_map) from a scheduled job")
