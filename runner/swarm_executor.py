#!/usr/bin/env python3
"""
swarm_executor.py - async multi-vendor API execution engine for code tasks.

Makes direct HTTP calls to Claude, OpenAI, DeepSeek, and Gemini APIs, bypassing
CLI subprocess overhead.  Two modes:
  * diff_mode  — model returns a unified diff (fast, low tokens)
  * agentic_mode — multi-turn conversation for complex tasks

Sync wrappers for the threaded runner:
    run_swarm(prompt, model, provider, cwd, timeout)  -> standard result dict
    run_swarm_dag(tasks, repo_path)                   -> list of result dicts

Env:
    SWARM_MAX_USD_HOUR  (default 8)   per-hour spend cap
    SWARM_MAX_USD_DAY   (default 30)  per-day spend cap
    ANTHROPIC_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY / GEMINI_API_KEY
"""
import os, sys, re, json, time, asyncio, logging, threading, fnmatch
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider_credentials


def _load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as source:
            for raw in source:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                # Standalone tournament workers need credentials, but importing
                # this module must not overwrite routing/test policy from .env.
                credential = (key.endswith(("_API_KEY", "_ACCESS_TOKEN", "_AUTH_TOKEN"))
                              or key in {"XAI_API_KEY", "GROK_API_KEY", "GROQ_API_KEY",
                                         "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                                         "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"})
                if credential:
                    os.environ.setdefault(key, value.split("#")[0].strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env()
provider_credentials.activate_aliases()
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------
PROVIDERS: Dict[str, dict] = {
    "claude": {
        "base_url": "https://api.anthropic.com/v1/messages",
        "key_env": "ANTHROPIC_API_KEY",
        "models": {"fast": "claude-haiku-4-5-20251001", "mid": "claude-sonnet-5",
                   "heavy": "claude-opus-4-8"},
        "max_concurrent": 50,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1/chat/completions",
        "key_env": "OPENAI_API_KEY",
        "models": {"fast": "gpt-5.4-nano", "mid": "gpt-5.4-mini", "heavy": "gpt-5.5"},
        "max_concurrent": 50,
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "key_env": "DEEPSEEK_API_KEY",
        "models": {"fast": "deepseek-v4-flash", "mid": "deepseek-v4-flash",
                   "heavy": "deepseek-v4-pro"},
        "max_concurrent": 50,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "key_env": "GEMINI_API_KEY",
        "models": {"fast": "gemini-3-flash", "mid": "gemini-3.5-flash",
                   "heavy": "gemini-3.1-pro"},
        "max_concurrent": 50,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "models": {"fast": "llama-3.1-8b-instant", "mid": "llama-3.3-70b-versatile",
                   "heavy": "llama-3.3-70b-versatile"},
        "max_concurrent": 30,
    },
    "xai": {
        "base_url": "https://api.x.ai/v1/chat/completions",
        "key_env": "XAI_API_KEY",
        "models": {"fast": "grok-build-0.1", "mid": "grok-build-0.1",
                   "heavy": "grok-4.3"},
        "max_concurrent": 50,
    },
}

# Pricing: (input $/Mtok, output $/Mtok)
_PRICES: Dict[str, tuple] = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    "gpt-5.5": (5.0, 30.0),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.6-sol": (5.0, 30.0),
    "o4-mini": (1.1, 4.4),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro": (0.435, 0.87),
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
    "gemini-3.5-flash": (1.50, 9.0),
    "gemini-3.1-pro": (2.0, 12.0),
    "gemini-3-flash": (0.50, 3.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "grok-4.5": (2.0, 6.0),
    "grok-4.3": (1.25, 2.50),
    "grok-4.20": (1.25, 2.50),
    "grok-build-0.1": (1.00, 2.00),
}

# Budget caps
MAX_USD_HOUR = float(os.environ.get("SWARM_MAX_USD_HOUR", "8"))
MAX_USD_DAY = float(os.environ.get("SWARM_MAX_USD_DAY", "30"))

# ---------------------------------------------------------------------------
# Budget tracker (thread-safe)
# ---------------------------------------------------------------------------
_budget_lock = threading.Lock()
_spend_log: List[tuple] = []  # (timestamp, usd)

DIFF_SYSTEM = (
    "You are a code-editing assistant. Given file contents and a task, return ONLY "
    "a unified diff (no markdown fences, no explanation). The diff must start with "
    "--- a/ and +++ b/ lines. If multiple files need changes, include all of them "
    "in one diff output. Do NOT include any text before or after the diff."
)

# Skip patterns for repo scanning
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
              "dist", "build", ".next", ".nuxt", "coverage", ".mypy_cache"}
_CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java",
              ".c", ".cpp", ".h", ".hpp", ".css", ".html", ".yaml", ".yml",
              ".json", ".toml", ".sql", ".sh", ".md", ".txt", ".cfg", ".ini",
              ".env.example", ".svelte", ".vue"}
_MAX_FILE_BYTES = 100_000


def _check_budget():
    """Raise RuntimeError if hourly or daily cap exceeded."""
    now = time.time()
    with _budget_lock:
        hour_spend = sum(u for t, u in _spend_log if now - t < 3600)
        day_spend = sum(u for t, u in _spend_log if now - t < 86400)
    if hour_spend >= MAX_USD_HOUR:
        raise RuntimeError(f"swarm hourly cap ${MAX_USD_HOUR:.2f} reached (${hour_spend:.2f})")
    if day_spend >= MAX_USD_DAY:
        raise RuntimeError(f"swarm daily cap ${MAX_USD_DAY:.2f} reached (${day_spend:.2f})")


def _record_spend(usd: float):
    with _budget_lock:
        _spend_log.append((time.time(), usd))
        # prune entries older than 25h
        cutoff = time.time() - 90000
        while _spend_log and _spend_log[0][0] < cutoff:
            _spend_log.pop(0)


def _cost(model: str, itok: int, otok: int) -> float:
    pin, pout = _PRICES.get(model, (3.0, 15.0))
    return itok / 1e6 * pin + otok / 1e6 * pout


def _empty_result(coder="swarm") -> dict:
    return {"text": "", "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
            "returncode": 1, "coder": coder}


# ---------------------------------------------------------------------------
# File cache helpers
# ---------------------------------------------------------------------------

def _read_repo_files(repo_path: str) -> Dict[str, str]:
    """Read all code files from repo, skip large/binary/irrelevant."""
    cache: Dict[str, str] = {}
    if not repo_path or not os.path.isdir(repo_path):
        return cache
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _CODE_EXTS:
                continue
            fpath = os.path.join(root, fname)
            try:
                if os.path.getsize(fpath) > _MAX_FILE_BYTES:
                    continue
                with open(fpath, errors="replace") as f:
                    cache[os.path.relpath(fpath, repo_path)] = f.read()
            except (OSError, PermissionError):
                pass
    return cache


def _extract_relevant_files(prompt: str, file_cache: Dict[str, str]) -> Dict[str, str]:
    """Find files mentioned in prompt by path or basename."""
    if not prompt:
        return {}
    relevant: Dict[str, str] = {}
    prompt_lower = prompt.lower()
    for relpath, content in file_cache.items():
        basename = os.path.basename(relpath).lower()
        if basename in prompt_lower or relpath in prompt or relpath.replace("/", " ") in prompt:
            relevant[relpath] = content
    # If nothing matched, return all files (small repos) or nothing (large repos)
    if not relevant and len(file_cache) <= 30:
        return dict(file_cache)
    return relevant


def _parse_diff(raw: str) -> List[dict]:
    """Parse unified diff text into list of {path, hunks} dicts.

    Handles common model output issues: markdown fences, explanation text.
    """
    # Strip markdown fences
    text = re.sub(r"```(?:diff)?\s*\n?", "", raw)
    text = re.sub(r"```\s*$", "", text, flags=re.M)

    # Find diff start
    start = re.search(r"^--- ", text, re.M)
    if start:
        text = text[start.start():]

    patches = []
    current = None
    for line in text.split("\n"):
        if line.startswith("--- a/") or line.startswith("--- "):
            path = re.sub(r"^--- (?:a/)?", "", line).strip()
            current = {"path": path, "hunks": []}
            patches.append(current)
        elif line.startswith("+++ b/") or line.startswith("+++ "):
            if current:
                current["path"] = re.sub(r"^\+\+\+ (?:b/)?", "", line).strip()
        elif line.startswith("@@") and current is not None:
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                current["hunks"].append({
                    "old_start": int(m.group(1)), "old_count": int(m.group(2) or 1),
                    "new_start": int(m.group(3)), "new_count": int(m.group(4) or 1),
                    "lines": [],
                })
        elif current and current["hunks"]:
            if line.startswith(("+", "-", " ")):
                current["hunks"][-1]["lines"].append(line)
    return patches


def _apply_diff(file_cache: Dict[str, str], diff_text: str) -> Dict[str, str]:
    """Parse and apply unified diff to file cache. Returns modified cache copy."""
    modified = dict(file_cache)
    patches = _parse_diff(diff_text)
    for patch in patches:
        path = patch["path"]
        original = modified.get(path, "")
        lines = original.split("\n") if original else []
        offset = 0
        for hunk in patch["hunks"]:
            pos = hunk["old_start"] - 1 + offset
            old_lines = [l[1:] for l in hunk["lines"] if l.startswith("-") or l.startswith(" ")]
            new_lines = [l[1:] for l in hunk["lines"] if l.startswith("+") or l.startswith(" ")]
            # Remove old lines and insert new
            end = pos + len([l for l in hunk["lines"] if l.startswith("-") or l.startswith(" ")])
            lines[pos:end] = new_lines
            offset += len(new_lines) - (end - pos)
        modified[path] = "\n".join(lines)
    return modified


def _write_repo_files(repo_path: str, original: Dict[str, str],
                      modified: Dict[str, str]):
    """Write only changed files back to disk."""
    for relpath, content in modified.items():
        if content != original.get(relpath):
            fpath = os.path.join(repo_path, relpath)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            try:
                with open(fpath, "w") as f:
                    f.write(content)
            except OSError as e:
                log.warning("write failed %s: %s", fpath, e)


# ---------------------------------------------------------------------------
# Provider-specific API call helpers (async)
# ---------------------------------------------------------------------------

async def _call_claude(session, model: str, messages: list,
                       system: str = "") -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return _empty_result("claude")
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    body: dict = {"model": model, "max_tokens": 8192, "messages": messages}
    if system:
        body["system"] = system
    try:
        async with session.post(PROVIDERS["claude"]["base_url"],
                                headers=headers, json=body, timeout=300) as r:
            data = await r.json()
        if r.status != 200:
            log.warning("claude %s: %s", r.status, data.get("error", {}).get("message", ""))
            return _empty_result("claude")
        text = "".join(b.get("text", "") for b in data.get("content", []))
        usage = data.get("usage", {})
        itok = usage.get("input_tokens", 0)
        otok = usage.get("output_tokens", 0)
        return {"text": text, "cost_usd": _cost(model, itok, otok),
                "input_tokens": itok, "output_tokens": otok,
                "returncode": 0, "coder": "claude"}
    except Exception as e:
        log.warning("claude error: %s", e)
        return _empty_result("claude")


async def _call_openai_compat(session, provider: str, model: str,
                              messages: list) -> dict:
    """Works for OpenAI & DeepSeek (same API shape)."""
    cfg = PROVIDERS[provider]
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        return _empty_result(provider)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"model": model, "messages": messages, "max_tokens": 8192,
            "temperature": 0.2}
    try:
        async with session.post(cfg["base_url"], headers=headers, json=body,
                                timeout=300) as r:
            data = await r.json()
        if r.status != 200:
            log.warning("%s %s: %s", provider, r.status,
                        data.get("error", {}).get("message", ""))
            return _empty_result(provider)
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})
        itok = usage.get("prompt_tokens", 0)
        otok = usage.get("completion_tokens", 0)
        return {"text": text, "cost_usd": _cost(model, itok, otok),
                "input_tokens": itok, "output_tokens": otok,
                "returncode": 0, "coder": provider}
    except Exception as e:
        log.warning("%s error: %s", provider, e)
        return _empty_result(provider)


async def _call_gemini(session, model: str, messages: list,
                       system: str = "") -> dict:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return _empty_result("gemini")
    url = (f"{PROVIDERS['gemini']['base_url']}/models/{model}"
           f":generateContent?key={key}")
    # Convert messages to Gemini format
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    body: dict = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    body["generationConfig"] = {"maxOutputTokens": 8192, "temperature": 0.2}
    try:
        async with session.post(url, json=body, timeout=300,
                                headers={"Content-Type": "application/json"}) as r:
            data = await r.json()
        if r.status != 200:
            log.warning("gemini %s: %s", r.status,
                        data.get("error", {}).get("message", ""))
            return _empty_result("gemini")
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        usage = data.get("usageMetadata", {})
        itok = usage.get("promptTokenCount", 0)
        otok = usage.get("candidatesTokenCount", 0)
        return {"text": text, "cost_usd": _cost(model, itok, otok),
                "input_tokens": itok, "output_tokens": otok,
                "returncode": 0, "coder": "gemini"}
    except Exception as e:
        log.warning("gemini error: %s", e)
        return _empty_result("gemini")


# ---------------------------------------------------------------------------
# Unified async dispatcher
# ---------------------------------------------------------------------------

_semaphores: Dict[str, asyncio.Semaphore] = {}


def _get_sem(provider: str) -> asyncio.Semaphore:
    if provider not in _semaphores:
        _semaphores[provider] = asyncio.Semaphore(
            PROVIDERS.get(provider, {}).get("max_concurrent", 50))
    return _semaphores[provider]


async def _dispatch(session, provider: str, model: str,
                    messages: list, system: str = "") -> dict:
    """Route to the right provider call, respecting semaphore."""
    sem = _get_sem(provider)
    async with sem:
        if provider == "claude":
            return await _call_claude(session, model, messages, system)
        elif provider in ("openai", "deepseek", "groq", "xai"):
            # Inject system as first message for OpenAI-compat
            if system:
                messages = [{"role": "system", "content": system}] + messages
            return await _call_openai_compat(session, provider, model, messages)
        elif provider == "gemini":
            return await _call_gemini(session, model, messages, system)
        return _empty_result(provider)


def _provider_for_model(model: str) -> str:
    """Resolve provider name from a model string."""
    for pname, cfg in PROVIDERS.items():
        if model in cfg["models"].values():
            return pname
    # Heuristic fallback
    if "claude" in model or "haiku" in model or "sonnet" in model or "opus" in model:
        return "claude"
    if "gpt" in model or model.startswith("o"):
        return "openai"
    if "deepseek" in model:
        return "deepseek"
    if "gemini" in model:
        return "gemini"
    if "llama" in model or "qwen" in model:
        return "groq"
    if "grok" in model:
        return "xai"
    return "claude"


# ---------------------------------------------------------------------------
# Execution modes
# ---------------------------------------------------------------------------

async def _execute_diff(session, provider: str, model: str, prompt: str,
                        file_cache: Dict[str, str]) -> dict:
    """Diff mode: send file contents + task, get a unified diff back."""
    relevant = _extract_relevant_files(prompt, file_cache)
    file_block = ""
    for path, content in relevant.items():
        file_block += f"\n--- {path} ---\n{content}\n"
    if not file_block:
        file_block = "(no files provided)"
    user_msg = f"FILES:\n{file_block}\n\nTASK:\n{prompt}"
    messages = [{"role": "user", "content": user_msg}]
    return await _dispatch(session, provider, model, messages, system=DIFF_SYSTEM)


async def _execute_agentic(session, provider: str, model: str, prompt: str,
                           file_cache: Dict[str, str],
                           max_turns: int = 5) -> dict:
    """Agentic mode: multi-turn for complex tasks."""
    relevant = _extract_relevant_files(prompt, file_cache)
    file_block = ""
    for path, content in list(relevant.items())[:15]:
        file_block += f"\n--- {path} ---\n{content}\n"
    system = ("You are an expert software engineer. Implement the requested changes. "
              "Return the complete modified file contents for each changed file, "
              "wrapped in ```path/to/file ... ``` blocks.")
    user_msg = prompt
    if file_block:
        user_msg = f"Relevant files:\n{file_block}\n\nTask:\n{prompt}"
    messages = [{"role": "user", "content": user_msg}]
    total_itok = total_otok = 0
    total_cost = 0.0
    last_text = ""
    for turn in range(max_turns):
        result = await _dispatch(session, provider, model, messages, system=system)
        total_itok += result["input_tokens"]
        total_otok += result["output_tokens"]
        total_cost += result["cost_usd"]
        last_text = result["text"]
        if result["returncode"] != 0:
            break
        # Simple completion check: if model doesn't ask a question, we're done
        if not last_text.rstrip().endswith("?"):
            break
        messages.append({"role": "assistant", "content": last_text})
        messages.append({"role": "user", "content": "Continue with the implementation."})
    return {"text": last_text, "cost_usd": total_cost, "input_tokens": total_itok,
            "output_tokens": total_otok, "returncode": 0 if last_text else 1,
            "coder": provider}


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def execute_one(prompt: str, model: str, provider: str = "",
                      cwd: str = "", mode: str = "diff",
                      timeout: float = 300, apply_diff: bool = True) -> dict:
    """Execute a single task. Returns the standard result dict."""
    try:
        _check_budget()
    except RuntimeError as e:
        r = _empty_result(provider or "swarm")
        r["text"] = str(e)
        return r

    provider = provider or _provider_for_model(model)
    file_cache = _read_repo_files(cwd) if cwd else {}

    try:
        import aiohttp
    except ImportError:
        log.warning("aiohttp not available, cannot execute swarm task")
        return _empty_result(provider)

    async with aiohttp.ClientSession() as session:
        if mode == "agentic":
            result = await asyncio.wait_for(
                _execute_agentic(session, provider, model, prompt, file_cache),
                timeout=timeout)
        else:
            result = await asyncio.wait_for(
                _execute_diff(session, provider, model, prompt, file_cache),
                timeout=timeout)

    _record_spend(result["cost_usd"])

    # Apply diff to files if in diff mode and we got output
    if apply_diff and mode == "diff" and cwd and result["returncode"] == 0 and result["text"]:
        try:
            modified = _apply_diff(file_cache, result["text"])
            _write_repo_files(cwd, file_cache, modified)
        except Exception as e:
            log.warning("diff apply failed: %s", e)

    return result


async def execute_batch(tasks: List[dict]) -> List[dict]:
    """Execute N tasks concurrently with per-provider semaphores.

    Each task dict: {prompt, model, provider?, cwd?, mode?, timeout?}
    """
    # Reset semaphores for fresh event loop
    _semaphores.clear()

    async def _run(t):
        return await execute_one(
            t["prompt"], t["model"], t.get("provider", ""),
            t.get("cwd", ""), t.get("mode", "diff"),
            t.get("timeout", 300))

    return await asyncio.gather(*[_run(t) for t in tasks])


async def execute_dag(tasks: List[dict], repo_path: str) -> List[dict]:
    """Execute a planner DAG respecting dependencies, maximizing parallelism.

    Each task dict: {slug, prompt, model, provider?, deps: [slug...], mode?}
    """
    _semaphores.clear()
    by_slug = {t["slug"]: t for t in tasks}
    results: Dict[str, dict] = {}
    done: set = set()
    pending = set(by_slug.keys())

    while pending:
        ready = [s for s in pending
                 if all(d in done for d in by_slug[s].get("deps", []))]
        if not ready:
            log.error("DAG deadlock: pending=%s done=%s", pending, done)
            for s in pending:
                results[s] = _empty_result("dag")
                results[s]["text"] = "deadlock: unresolvable deps"
            break

        async def _run_task(slug):
            t = by_slug[slug]
            r = await execute_one(
                t["prompt"], t["model"], t.get("provider", ""),
                repo_path, t.get("mode", "diff"))
            return slug, r

        batch = await asyncio.gather(*[_run_task(s) for s in ready])
        for slug, result in batch:
            results[slug] = result
            done.add(slug)
            pending.discard(slug)

    return [results.get(t["slug"], _empty_result("dag")) for t in tasks]


async def speculative_execute(task: dict,
                              providers: List[str]) -> dict:
    """Race same task across 2+ providers, take first good result."""
    _semaphores.clear()

    async def _attempt(prov):
        models = PROVIDERS.get(prov, {}).get("models", {})
        model = task.get("model_tier", "mid")
        model_name = models.get(model, models.get("mid", ""))
        if not model_name:
            return _empty_result(prov)
        return await execute_one(
            task["prompt"], model_name, prov,
            task.get("cwd", ""), task.get("mode", "diff"))

    coros = [_attempt(p) for p in providers]
    # Use as_completed to get first success
    for coro in asyncio.as_completed(coros):
        result = await coro
        if result["returncode"] == 0 and result["text"]:
            return result
    return _empty_result("speculative")


# ---------------------------------------------------------------------------
# Sync wrappers (for threaded runner)
# ---------------------------------------------------------------------------

_SYNC_LOOP = None
_SYNC_THREAD = None
_SYNC_LOCK = threading.Lock()

def _persistent_loop():
    global _SYNC_LOOP, _SYNC_THREAD
    with _SYNC_LOCK:
        if _SYNC_LOOP and _SYNC_THREAD and _SYNC_THREAD.is_alive():
            return _SYNC_LOOP
        ready = threading.Event()
        def serve():
            global _SYNC_LOOP
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            _SYNC_LOOP = loop; ready.set(); loop.run_forever()
        _SYNC_THREAD = threading.Thread(target=serve, name="swarm-async-loop", daemon=True)
        _SYNC_THREAD.start(); ready.wait(5)
        return _SYNC_LOOP

def run_swarm(prompt: str, model: str, provider: str = "", cwd: str = "",
              timeout: float = 300, mode: str = "diff", apply_diff: bool = True,
              repo_cache: bool = True) -> dict:
    """Synchronous entrypoint matching claude_cli.run() return shape.

    Safe to call from threaded code — creates its own event loop.
    """
    if not prompt:
        return _empty_result("swarm")
    try:
        loop = _persistent_loop()
        future = asyncio.run_coroutine_threadsafe(
            execute_one(prompt, model, provider, cwd, mode, timeout, apply_diff), loop)
        return future.result(timeout=timeout + 30)
    except Exception as e:
        log.warning("run_swarm error: %s", e)
        r = _empty_result(provider or "swarm")
        r["text"] = str(e)
        return r


def run_swarm_dag(tasks: List[dict], repo_path: str) -> List[dict]:
    """Synchronous wrapper for execute_dag."""
    if not tasks:
        return []
    try:
        loop = asyncio.new_event_loop()
        results = loop.run_until_complete(execute_dag(tasks, repo_path))
        loop.close()
        return results
    except Exception as e:
        log.warning("run_swarm_dag error: %s", e)
        return [_empty_result("dag") for _ in tasks]


# ---------------------------------------------------------------------------
# CLI for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="swarm_executor quick test")
    ap.add_argument("prompt", nargs="?", default="Return a diff that adds a comment '# hello' to the top of README.md")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--provider", default="")
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--mode", default="diff", choices=["diff", "agentic"])
    args = ap.parse_args()
    r = run_swarm(args.prompt, args.model, args.provider, args.cwd, mode=args.mode)
    print(json.dumps({k: v for k, v in r.items() if k != "raw"}, indent=2))
