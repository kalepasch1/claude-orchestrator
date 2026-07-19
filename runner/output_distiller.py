"""Agent output distillation — extract reasoning traces, compress to recipes."""
import sys, os, re, json, time, threading, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("output_distiller")
try:
    import db
except Exception:
    db = None

ENABLED = os.environ.get("ORCH_OUTPUT_DISTILLER_ENABLED", "true").lower() in ("true", "1", "yes")

_READ_PAT = re.compile(r"(?:Read|read|cat|open|view)\s+['\"]?([^\s'\"]+\.\w+)")
_DECISION_PAT = re.compile(r"(?:I'll|Let me|The (?:issue|fix|problem|solution) is|I need to)\s+(.{10,80})", re.IGNORECASE)
_ERROR_PAT = re.compile(r"(?:Error|error|FAIL|Failed|Exception):\s*(.{10,120})")
_FIXED_PAT = re.compile(r"(?:Fixed|Resolved|fixed|resolved)\s+(?:by\s+)?(.{10,80})")
_DIFF_FILE = re.compile(r"^(?:diff --git a/|[+]{3} b/)(.+)$", re.MULTILINE)


def _slug_prefix(slug):
    parts = (slug or "").split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else slug or "unknown"


class _Distiller:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}  # (slug_prefix, project_id) -> recipe
        self._cache_at = 0
        self._stats = {"recipes_stored": 0, "recipes_used": 0, "avg_length": 0}

    def distill(self, task, agent_output, diff_text, model, cost_usd):
        if not ENABLED:
            return None
        out = agent_output or ""
        files_read = list(set(_READ_PAT.findall(out)))[:10]
        files_modified = list(set(_DIFF_FILE.findall(diff_text or "")))[:10]
        decisions = [m.group(1).strip() for m in _DECISION_PAT.finditer(out)][:5]
        errors = [m.group(1).strip() for m in _ERROR_PAT.finditer(out)][:3]
        fixes = [m.group(1).strip() for m in _FIXED_PAT.finditer(out)][:3]

        approach = decisions[0] if decisions else "standard implementation"
        pitfalls = "; ".join(f"{e} -> {f}" for e, f in zip(errors, fixes)) if errors and fixes else ""

        recipe_lines = [f"RECIPE: {_slug_prefix(task.get('slug', ''))}"]
        if files_read:
            recipe_lines.append(f"READ: {', '.join(files_read[:5])}")
        if files_modified:
            recipe_lines.append(f"MODIFY: {', '.join(files_modified[:5])}")
        recipe_lines.append(f"APPROACH: {approach[:120]}")
        if pitfalls:
            recipe_lines.append(f"PITFALLS: {pitfalls[:200]}")
        recipe_text = "\n".join(recipe_lines)

        return {
            "recipe": recipe_text,
            "steps": decisions[:5],
            "key_decisions": decisions[:3],
            "files_pattern": files_modified[:5],
            "files_read": files_read[:5],
            "model": model,
            "cost_usd": cost_usd,
        }

    def store_recipe(self, slug_prefix, project_id, recipe):
        if not ENABLED or not db:
            return
        try:
            row = {
                "slug_prefix": slug_prefix,
                "project_id": project_id,
                "recipe": recipe.get("recipe", ""),
                "files_pattern": json.dumps(recipe.get("files_pattern", [])),
                "model": recipe.get("model", ""),
                "success_count": 1,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            existing = db.select("agent_recipes",
                                 f"slug_prefix=eq.{slug_prefix}&project_id=eq.{project_id}&limit=1")
            if existing:
                count = (existing[0].get("success_count") or 0) + 1
                db.update("agent_recipes", {"success_count": count, "recipe": row["recipe"],
                           "updated_at": row["updated_at"]},
                          f"slug_prefix=eq.{slug_prefix}&project_id=eq.{project_id}")
            else:
                db.insert("agent_recipes", row)
            with self._lock:
                self._cache[(slug_prefix, project_id)] = recipe
                self._stats["recipes_stored"] += 1
        except Exception as e:
            _log.debug("store_recipe failed: %s", e)

    def find_recipe(self, task, project_id):
        if not ENABLED:
            return None
        prefix = _slug_prefix(task.get("slug", ""))
        key = (prefix, project_id)
        with self._lock:
            if key in self._cache and time.time() - self._cache_at < 300:
                self._stats["recipes_used"] += 1
                return self._cache[key]
        if not db:
            return None
        try:
            rows = db.select("agent_recipes",
                             f"slug_prefix=eq.{prefix}&project_id=eq.{project_id}"
                             f"&order=success_count.desc&limit=1")
            if rows:
                recipe = {"recipe": rows[0].get("recipe", ""), "success_count": rows[0].get("success_count", 0)}
                with self._lock:
                    self._cache[key] = recipe
                    self._cache_at = time.time()
                    self._stats["recipes_used"] += 1
                return recipe
        except Exception as e:
            _log.debug("find_recipe failed: %s", e)
        return None

    def inject_recipe(self, prompt, recipe):
        if not recipe or not recipe.get("recipe"):
            return prompt
        block = (f"\n\n## Proven Recipe\n"
                 f"A previous successful agent used this approach for a similar task:\n"
                 f"```\n{recipe['recipe'][:600]}\n```\n"
                 f"Follow this recipe unless you find a better approach.\n")
        return prompt + block

    def stats(self):
        with self._lock:
            return dict(self._stats, enabled=ENABLED)


_distiller = _Distiller()

def distill(task, agent_output, diff_text="", model="", cost_usd=0):
    try: return _distiller.distill(task, agent_output, diff_text, model, cost_usd)
    except Exception: return None

def store_recipe(slug_prefix, project_id, recipe):
    try: _distiller.store_recipe(slug_prefix, project_id, recipe)
    except Exception: pass

def find_recipe(task, project_id):
    try: return _distiller.find_recipe(task, project_id)
    except Exception: return None

def inject_recipe(prompt, recipe):
    try: return _distiller.inject_recipe(prompt, recipe)
    except Exception: return prompt

def stats():
    try: return _distiller.stats()
    except Exception: return {"enabled": False}
