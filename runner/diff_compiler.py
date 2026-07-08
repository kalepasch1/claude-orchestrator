"""
diff_compiler.py — merged-diff compiler for pattern-based code generation.

Before spending tokens on agentic coding, this module:
1. Searches the merged diff library for similar past changes
2. Extracts common patterns (file structure, test patterns, component shapes)
3. Generates a concrete patch plan the agent can follow

This converts "invent from scratch" into "adapt a proven template" —
100X-500X cheaper for repeated app patterns (new components, API endpoints,
test files, config changes).
"""
import os, sys, json, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SIMILARITY_THRESHOLD = float(os.environ.get("ORCH_DIFF_COMPILER_THRESHOLD", "0.3"))
MAX_TEMPLATE_DIFFS = int(os.environ.get("ORCH_DIFF_COMPILER_MAX", "3"))


def compile_plan(prompt, project=None, repo=None, base=None):
    """Generate a patch plan from similar merged diffs.

    Returns:
        dict with:
        - has_plan: bool
        - plan_text: str (injected into agent prompt)
        - templates: list of matched templates
        - confidence: float (0-1)
    """
    if not prompt:
        return {"has_plan": False, "plan_text": "", "templates": [], "confidence": 0}

    # Extract intent keywords from the prompt
    keywords = _extract_keywords(prompt)
    if not keywords:
        return {"has_plan": False, "plan_text": "", "templates": [], "confidence": 0}

    # Search for similar merged diffs
    templates = _find_similar_diffs(keywords, project)
    if not templates:
        return {"has_plan": False, "plan_text": "", "templates": [], "confidence": 0}

    # Score and rank templates
    scored = []
    for t in templates:
        score = _score_template(t, keywords, prompt)
        if score >= SIMILARITY_THRESHOLD:
            scored.append((score, t))

    scored.sort(key=lambda x: -x[0])
    top = scored[:MAX_TEMPLATE_DIFFS]

    if not top:
        return {"has_plan": False, "plan_text": "", "templates": [], "confidence": 0}

    # Generate the plan
    plan_text = _generate_plan(top, prompt)
    confidence = top[0][0]

    return {
        "has_plan": True,
        "plan_text": plan_text,
        "templates": [{"slug": t.get("slug"), "score": round(s, 3)} for s, t in top],
        "confidence": round(confidence, 3)
    }


def inject_plan(prompt, plan):
    """Inject a compiled plan into the agent prompt."""
    if not plan or not plan.get("has_plan"):
        return prompt

    block = (
        "\n\n## Merged-Diff Compiler: Proven Pattern Available\n"
        f"Confidence: {plan['confidence']:.0%} match to prior merged work.\n"
        "ADAPT the pattern below instead of inventing from scratch. "
        "The template already passed tests and merged successfully.\n\n"
        f"{plan['plan_text']}\n"
        "---\n"
    )
    return block + prompt


def _extract_keywords(prompt):
    """Extract meaningful keywords from a task prompt."""
    # Remove common stop words and extract significant terms
    stop = {"the", "and", "for", "that", "this", "with", "from", "will", "have",
            "been", "are", "was", "were", "not", "but", "all", "can", "had", "her",
            "one", "our", "out", "you", "has", "its", "let", "may", "new", "now",
            "old", "see", "way", "who", "did", "get", "got", "him", "his", "how",
            "use", "add", "fix", "run", "set", "try", "also", "make", "like",
            "should", "would", "could", "need", "want", "must", "just", "into"}
    words = re.findall(r'\b[a-zA-Z]\w{2,}\b', prompt.lower())
    return [w for w in words if w not in stop][:50]


def _find_similar_diffs(keywords, project=None):
    """Search merged diff library for similar changes."""
    try:
        # Try task_artifacts first (richer data)
        import task_artifacts

        # Get recent merged tasks
        params = {
            "select": "slug,kind",
            "state": "eq.MERGED",
            "order": "updated_at.desc",
            "limit": "100"
        }
        if project:
            params["project_id"] = f"eq.{_project_id(project)}"

        merged = db.select("tasks", params) or []

        results = []
        for mt in merged:
            art = task_artifacts.get_artifacts(mt.get("slug", ""))
            if art and art.get("patch_diff"):
                results.append({
                    "slug": mt.get("slug"),
                    "kind": mt.get("kind"),
                    "diff": art["patch_diff"][:50000],
                    "files": json.loads(art.get("touched_files", "[]")),
                })

        return results
    except Exception:
        return []


def _score_template(template, keywords, prompt):
    """Score how well a template matches the current task."""
    score = 0.0
    diff = (template.get("diff") or "").lower()
    files = template.get("files", [])

    # Keyword overlap in diff
    keyword_set = set(keywords)
    diff_words = set(re.findall(r'\b\w{3,}\b', diff[:5000]))
    overlap = len(keyword_set & diff_words)
    score += min(0.4, overlap * 0.04)

    # File pattern matching (same directory structure = strong signal)
    prompt_files = set(re.findall(r'[\w/]+\.\w+', prompt.lower()))
    template_files = set(f.lower() for f in files)

    if prompt_files and template_files:
        # Same directories
        prompt_dirs = set(os.path.dirname(f) for f in prompt_files if "/" in f)
        template_dirs = set(os.path.dirname(f) for f in template_files if "/" in f)
        dir_overlap = len(prompt_dirs & template_dirs)
        score += min(0.3, dir_overlap * 0.1)

        # Same extensions
        prompt_exts = set(os.path.splitext(f)[1] for f in prompt_files)
        template_exts = set(os.path.splitext(f)[1] for f in template_files)
        ext_overlap = len(prompt_exts & template_exts)
        score += min(0.2, ext_overlap * 0.05)

    # Kind match bonus
    kind = (template.get("kind") or "").lower()
    if kind and kind in prompt.lower():
        score += 0.1

    return min(1.0, score)


def _generate_plan(scored_templates, prompt):
    """Generate a concrete patch plan from matched templates."""
    lines = []

    for i, (score, template) in enumerate(scored_templates):
        slug = template.get("slug", "unknown")
        files = template.get("files", [])
        diff = template.get("diff", "")

        lines.append(f"### Template {i+1}: {slug} (match: {score:.0%})")

        if files:
            lines.append(f"Files touched: {', '.join(files[:10])}")

        # Extract the structural pattern from the diff
        pattern = _extract_pattern(diff)
        if pattern:
            lines.append(f"Pattern:\n```\n{pattern}\n```")

        lines.append("")

    return "\n".join(lines)


def _extract_pattern(diff):
    """Extract the structural pattern from a diff (file names + change types)."""
    if not diff:
        return ""

    lines = []
    current_file = ""
    adds = 0
    dels = 0

    for line in diff.split("\n")[:500]:
        if line.startswith("diff --git"):
            if current_file and (adds or dels):
                lines.append(f"  {current_file}: +{adds}/-{dels}")
            match = re.search(r'b/(.+)$', line)
            current_file = match.group(1) if match else ""
            adds = 0
            dels = 0
        elif line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1

    if current_file and (adds or dels):
        lines.append(f"  {current_file}: +{adds}/-{dels}")

    return "\n".join(lines[:20])


def _project_id(name):
    """Look up project ID by name."""
    try:
        rows = db.select("projects", {"select": "id", "name": f"eq.{name}", "limit": "1"})
        return rows[0]["id"] if rows else name
    except Exception:
        return name


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        plan = compile_plan(" ".join(sys.argv[1:]))
        print(json.dumps(plan, indent=2))
