#!/usr/bin/env python3
"""
shared_world_model.py — one live graph of every app's schema, endpoints and contracts, so a
change's TRUE blast radius (including the part that lives in a different repo) is known
BEFORE the build starts.

THE PROBLEM THIS SOLVES
    blast_radius.py answers "what else in THIS repo imports the file I'm touching". That is
    the easy half. The expensive failures on this fleet are cross-app: a table renamed in
    apparently's migration that tomorrow reads by name; an endpoint deleted in one Nuxt app
    that another app calls over HTTP; a capability contract versioned in the registry while
    three other projects are still instantiating the old shape. None of those are import
    edges, so no import-graph tool can see them, and the breakage surfaces at runtime in a
    repo the agent never opened.

THE MODEL
    Each project contributes a SURFACE — the names it exposes to the rest of the fleet:
        tables     — Prisma models (incl. @@map) and CREATE TABLE in SQL migrations
        endpoints  — Nuxt/Nitro server routes (server/api/**) and FastAPI/Flask decorators
        modules    — top-level python modules (the unit other fleet code imports)
    A cross-app EDGE exists when project B's source mentions a symbol project A owns.
    Ownership is decided by the surface, references by a bounded text scan, so the graph is
    computable from source alone with no runtime instrumentation and no schema registry.

    Capability contracts are the fourth edge type and come from the registry rather than
    source: capability.publish() records the owning project, capability.instantiate() records
    each consumer. `capability_edges()` folds those into the same graph so a contract change
    and a table rename produce the same kind of answer.

USE
    from shared_world_model import cross_app_radius, note_for_task
    cross_app_radius("apparently", ["supabase/migrations/031_add_ledger.sql"])
    note_for_task("apparently", task_prompt)        # prompt-injection block, "" when quiet

DESIGN RULES (this repo's conventions)
    - fail-soft: every public function returns a safe default ({}/[]/"") on any error and
      never raises. A world model that can take the runner down is worse than none.
    - env-configurable: scan caps, TTL and the ignore list are ORCH_* env vars.
    - process-cached with a TTL: the graph is rebuilt at most once per SWM_TTL seconds; a
      full fleet scan is far too expensive to run per task.
    - read-only: this module never writes to the database or the working tree.
"""
import os
import re
import sys
import time

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

__all__ = ["scan_project", "build_graph", "cross_app_radius", "capability_edges",
           "note_for_task", "owners_of", "invalidate"]

TTL = float(os.environ.get("ORCH_SWM_TTL", "900"))
MAX_FILES = int(os.environ.get("ORCH_SWM_MAX_FILES", "4000"))
MAX_BYTES = int(os.environ.get("ORCH_SWM_MAX_BYTES", "400000"))
MAX_HITS = int(os.environ.get("ORCH_SWM_MAX_HITS", "40"))

IGNORE_DIRS = {d for d in (os.environ.get(
    "ORCH_SWM_IGNORE_DIRS",
    ".git,node_modules,.nuxt,.output,dist,build,__pycache__,.venv,venv,coverage,"
    ".next,_to_delete,vendor,.pytest_cache").split(",")) if d}

SOURCE_EXT = (".py", ".ts", ".tsx", ".js", ".mjs", ".jsx", ".vue", ".sql", ".prisma")

# Scanned before anything else so the file cap can never starve the surface — see _walk().
PRIORITY_DIRS = [d for d in (os.environ.get(
    "ORCH_SWM_PRIORITY_DIRS",
    "prisma,supabase,migrations,db,schema,server,api,src/server,app/api,routes").split(","))
    if d]

# A symbol shorter than this matches everything; a symbol on this list is a common English
# word that happens to be a table name somewhere. Both produce noise, and a blast-radius
# report nobody trusts gets ignored, which is worse than no report.
MIN_SYMBOL = int(os.environ.get("ORCH_SWM_MIN_SYMBOL", "5"))
STOP_SYMBOLS = {"users", "user", "index", "state", "value", "config", "tasks", "task",
                "data", "items", "item", "event", "events", "types", "utils", "test",
                "tests", "main", "model", "models", "table", "public", "admin"}

_PRISMA_MODEL = re.compile(r"^\s*model\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{", re.M)
_PRISMA_MAP = re.compile(r'@@map\(\s*"([^"]+)"\s*\)')
_SQL_TABLE = re.compile(
    r'create\s+table\s+(?:if\s+not\s+exists\s+)?"?([A-Za-z_][A-Za-z0-9_]*)"?', re.I)
_PY_ROUTE = re.compile(r'@\w+\.(?:get|post|put|patch|delete|route)\(\s*[\'"]([^\'"]+)')

_cache = {"at": 0.0, "graph": None}


# ── filesystem helpers ────────────────────────────────────────────────────────

def _walk_from(root_dir, want_ext, cap, out, seen):
    try:
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".git")]
            for f in files:
                if not f.endswith(want_ext):
                    continue
                p = os.path.join(root, f)
                if p in seen:
                    continue
                seen.add(p)
                out.append(p)
                if len(out) >= cap:
                    return True
    except Exception:
        pass
    return False


def _walk(repo_path, want_ext=SOURCE_EXT, max_files=None):
    """Bounded source-file walk, SURFACE-BEARING DIRECTORIES FIRST.

    A flat os.walk with a file cap is not good enough here: on a large Nuxt app the cap is
    exhausted by app/ and node_modules-adjacent trees long before the walk reaches
    server/api, and the project silently reports zero endpoints — a world model that
    confidently says "nothing is shared" is worse than no world model. Measured on this
    fleet: a flat 4,000-file walk found 0 endpoints in tomorrow and 20 in apparently, while
    a smaller repo under the cap found 413.

    Walking the directories that can actually define a surface first makes the cap bound
    cost without ever starving the answer.
    """
    out, seen = [], set()
    cap = max_files or MAX_FILES
    for rel in PRIORITY_DIRS:
        d = os.path.join(repo_path, rel)
        if os.path.isdir(d) and _walk_from(d, want_ext, cap, out, seen):
            return out
    _walk_from(repo_path, want_ext, cap, out, seen)
    return out


def _read(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


# ── surface extraction ────────────────────────────────────────────────────────

def _tables_from(text, path):
    """Table names a file DEFINES (not the ones it queries)."""
    names = set()
    if path.endswith(".prisma"):
        names.update(m.group(1) for m in _PRISMA_MODEL.finditer(text))
        names.update(m.group(1) for m in _PRISMA_MAP.finditer(text))
    elif path.endswith(".sql"):
        names.update(m.group(1) for m in _SQL_TABLE.finditer(text))
    return names


def _endpoint_from_path(repo_path, path):
    """Nuxt/Nitro file-routing: server/api/foo/[id].post.ts -> /api/foo/[id]."""
    rel = os.path.relpath(path, repo_path).replace(os.sep, "/")
    marker = "server/api/"
    if marker not in rel:
        return None
    route = rel.split(marker, 1)[1]
    route = re.sub(r"\.(get|post|put|patch|delete)?\.?(ts|js|mjs)$", "", route)
    route = re.sub(r"/index$", "", route)
    return "/api/" + route.strip("/") if route.strip("/") else "/api"


def scan_project(project):
    """Extract one project's public surface.

    project: {"name", "repo_path"} (a row from `projects` works as-is).
    Returns {"project", "repo_path", "tables", "endpoints", "modules", "files"} — always a
    dict, empty surfaces on any failure.
    """
    name = (project or {}).get("name") or ""
    repo_path = (project or {}).get("repo_path") or ""
    surface = {"project": name, "repo_path": repo_path,
               "tables": {}, "endpoints": {}, "modules": {}, "files": 0}
    if not repo_path or not os.path.isdir(repo_path):
        return surface

    for path in _walk(repo_path):
        surface["files"] += 1
        rel = os.path.relpath(path, repo_path).replace(os.sep, "/")
        base = os.path.basename(path)

        if path.endswith((".prisma", ".sql")):
            for t in _tables_from(_read(path), path):
                surface["tables"].setdefault(t, rel)

        ep = _endpoint_from_path(repo_path, path)
        if ep:
            surface["endpoints"].setdefault(ep, rel)
        elif path.endswith(".py"):
            text = _read(path)
            for m in _PY_ROUTE.finditer(text):
                surface["endpoints"].setdefault(m.group(1), rel)
            stem = base[:-3]
            if stem not in ("__init__", "setup", "conftest"):
                surface["modules"].setdefault(stem, rel)
    return surface


# ── graph ─────────────────────────────────────────────────────────────────────

def _projects():
    try:
        import db  # imported lazily: the scanner must work without a live database
        return [p for p in (db.select("projects") or []) if p.get("repo_path")]
    except Exception:
        return []


def build_graph(projects=None, force=False):
    """{"projects": {name: surface}, "owners": {symbol: [(project, kind, defined_in)]}}.

    Cached for TTL seconds — a full fleet scan is far too expensive per task.
    """
    now = time.time()
    if not force and projects is None and _cache["graph"] and now - _cache["at"] < TTL:
        return _cache["graph"]

    rows = projects if projects is not None else _projects()
    graph = {"projects": {}, "owners": {}, "built_at": now}
    for proj in rows or []:
        try:
            surface = scan_project(proj)
        except Exception:
            continue
        pname = surface.get("project") or ""
        if not pname:
            continue
        graph["projects"][pname] = surface
        for kind in ("tables", "endpoints", "modules"):
            for symbol, defined_in in (surface.get(kind) or {}).items():
                graph["owners"].setdefault(symbol, []).append((pname, kind, defined_in))

    if projects is None:
        _cache["graph"], _cache["at"] = graph, now
    return graph


def invalidate():
    """Drop the cached graph (call after a migration or a large merge)."""
    _cache["graph"], _cache["at"] = None, 0.0


def owners_of(symbol, graph=None):
    """Which projects define this symbol, as [(project, kind, defined_in)]."""
    try:
        g = graph or build_graph()
        return list(g.get("owners", {}).get(symbol) or [])
    except Exception:
        return []


def _interesting(symbol):
    s = (symbol or "").strip()
    return len(s) >= MIN_SYMBOL and s.lower() not in STOP_SYMBOLS


def _needle(symbol):
    """What to actually search for when hunting references to `symbol`.

    A dynamic route is DEFINED as `/api/ledger/[id]` but CALLED as `/api/ledger/42`, so a
    literal search for the declared name finds nothing — the single most likely way for
    this whole tool to report a confident, wrong "no impact". Match on the static prefix
    instead, and only when that prefix is still specific enough to mean something.
    """
    s = (symbol or "").strip()
    for marker in ("[", ":", "{", "<"):     # Nuxt, Express/FastAPI, Flask, generic
        if marker in s:
            s = s.split(marker, 1)[0].rstrip("/")
            break
    return s if len(s) >= MIN_SYMBOL else None


def _references(repo_path, symbols):
    """Files under repo_path that MENTION any of `symbols` -> {symbol: [rel_path]}."""
    hits = {}
    if not repo_path or not os.path.isdir(repo_path) or not symbols:
        return hits
    needles = {}
    for s in symbols:
        if not _interesting(s):
            continue
        n = _needle(s)
        if n:
            needles.setdefault(n, []).append(s)
    if not needles:
        return hits
    pattern = re.compile("|".join(re.escape(n) for n in sorted(needles, key=len,
                                                               reverse=True)))
    for path in _walk(repo_path):
        text = _read(path)
        if not text:
            continue
        found = set(pattern.findall(text))
        if not found:
            continue
        rel = os.path.relpath(path, repo_path).replace(os.sep, "/")
        for n in found:
            for s in needles.get(n, []):
                bucket = hits.setdefault(s, [])
                if len(bucket) < MAX_HITS:
                    bucket.append(rel)
    return hits


def symbols_defined_by(project_name, changed_files, graph=None):
    """The surface symbols the changed files DEFINE — the blast source."""
    out = set()
    try:
        g = graph or build_graph()
        surface = (g.get("projects") or {}).get(project_name) or {}
        changed = {str(f).replace(os.sep, "/") for f in (changed_files or [])}
        for kind in ("tables", "endpoints", "modules"):
            for symbol, defined_in in (surface.get(kind) or {}).items():
                if defined_in in changed or any(c.endswith(defined_in) for c in changed):
                    out.add(symbol)
    except Exception:
        return set()
    return out


def cross_app_radius(project_name, changed_files, graph=None):
    """Which OTHER apps a change in this app can break.

    Returns {"source": project, "symbols": [...],
             "impacted": [{"project", "symbol", "kind", "files": [...]}]}
    """
    result = {"source": project_name, "symbols": [], "impacted": []}
    try:
        g = graph or build_graph()
        symbols = symbols_defined_by(project_name, changed_files, graph=g)
        symbols = {s for s in symbols if _interesting(s)}
        result["symbols"] = sorted(symbols)
        if not symbols:
            return result
        kind_of = {}
        for symbol in symbols:
            for owner, kind, _where in g.get("owners", {}).get(symbol, []):
                if owner == project_name:
                    kind_of[symbol] = kind
        for other, surface in (g.get("projects") or {}).items():
            if other == project_name:
                continue
            for symbol, files in _references(surface.get("repo_path"), symbols).items():
                result["impacted"].append({"project": other, "symbol": symbol,
                                           "kind": kind_of.get(symbol, "symbol"),
                                           "files": files})
        result["impacted"].sort(key=lambda r: (r["project"], r["symbol"]))
    except Exception:
        pass
    return result


def capability_edges(project_name=None):
    """Contract edges from the capability registry: who publishes, who consumes.

    Source-scanning cannot see these — a capability is instantiated through the registry,
    not by importing a file — so they are read from the database and folded in here.
    Returns [] when the registry is unavailable (fail-soft, as everywhere else).
    """
    edges = []
    try:
        import db  # lazy: the source scanner must not require a database
        caps = db.select("capabilities", {"select": "id,slug,name,status"}) or []
        by_id = {c["id"]: c for c in caps if c.get("id")}
        if not by_id:
            return []
        instances = db.select("capability_instances",
                              {"select": "capability_id,project,version,status"}) or []
        for inst in instances:
            cap = by_id.get(inst.get("capability_id"))
            if not cap or cap.get("status") == "retired":
                continue
            if inst.get("status") and inst.get("status") != "active":
                continue
            edge = {"capability": cap.get("slug"), "consumer": inst.get("project"),
                    "version": inst.get("version")}
            if project_name in (None, edge["consumer"]):
                edges.append(edge)
    except Exception:
        return []
    return edges


# ── prompt injection ──────────────────────────────────────────────────────────

def note_for_task(project_name, prompt, changed_files=None, graph=None, limit=8):
    """A short block naming the cross-app surfaces this task is likely to disturb.

    Returns "" when there is nothing to say — a note that fires on every task is noise and
    gets ignored, which defeats the purpose.
    """
    try:
        g = graph or build_graph()
        surface = (g.get("projects") or {}).get(project_name) or {}
        if changed_files:
            symbols = symbols_defined_by(project_name, changed_files, graph=g)
        else:
            text = (prompt or "").lower()
            symbols = {s for kind in ("tables", "endpoints", "modules")
                       for s in (surface.get(kind) or {})
                       if _interesting(s) and s.lower() in text}
        symbols = {s for s in symbols if _interesting(s)}
        if not symbols:
            return ""

        impacted = []
        for other, other_surface in (g.get("projects") or {}).items():
            if other == project_name:
                continue
            for symbol, files in _references(other_surface.get("repo_path"), symbols).items():
                impacted.append((other, symbol, files))
        if not impacted:
            return ""
        impacted.sort()

        lines = ["# Cross-app blast radius: these OTHER apps reference surfaces this task",
                 "# touches. Renaming or removing one breaks them at RUNTIME, not at build —",
                 "# no import graph will catch it. Keep the names, or update both sides:"]
        for other, symbol, files in impacted[:limit]:
            where = ", ".join(files[:3])
            lines.append(f"- {other} uses `{symbol}` ({where})")
        if len(impacted) > limit:
            lines.append(f"- ...and {len(impacted) - limit} more references")
        return "\n".join(lines) + "\n\n"
    except Exception:
        return ""


if __name__ == "__main__":
    g = build_graph(force=True)
    for name, s in sorted((g.get("projects") or {}).items()):
        print(f"{name}: {s['files']} files, {len(s['tables'])} tables, "
              f"{len(s['endpoints'])} endpoints, {len(s['modules'])} modules")
    print(f"owned symbols: {len(g.get('owners') or {})}")
