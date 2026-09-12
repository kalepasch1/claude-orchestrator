#!/usr/bin/env python3
"""model_id_audit.py — are the model IDs this fleet pins still real?

WHY THIS EXISTS. On 2026-08-24 the fleet could not do any work, and one of the
reasons was that `gemini-2.5-pro` — the default agentic coder — had been retired
by Google. It returned 404 forever. Three more pinned IDs were in the same
state: `gemini-2.0-flash`, `gemini-4.0-flash`, `gemini-2.5-flash-lite`.

A retired ID is a distinct failure from an empty account and needs a different
response. Nobody notices it, because it looks exactly like every other provider
error in the log, and because a model ID is a string in a config file that no
test ever dereferences. Vendors retire IDs on their own schedule; this fleet
finds out when a task fails.

Every provider except xAI serves its catalogue WITHOUT credit — Google's
ListModels, OpenAI's /v1/models and DeepSeek's /models all answered 200 while
those same accounts were refusing completions for lack of funds. So this check
keeps working precisely when the fleet is most broken, which is when it is
needed. Anthropic has no such endpoint and the fleet runs Claude through a
subscription CLI rather than by ID, so `claude-*` names are reported as
unverifiable rather than guessed at.

    python3 runner/tools/model_id_audit.py            # audit, exit 1 if dead
    python3 runner/tools/model_id_audit.py --list     # also list live IDs
    python3 runner/tools/model_id_audit.py --json     # machine-readable

Exit 0 clean, 1 dead IDs found, 2 could not determine (fail-closed: an
unreachable catalogue is not evidence that an ID is fine).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

#: Routing code is scoped to the runner; test suites are not. This fleet has
#: them in `tests/`, `runner/tests/`, `beethoven/tests/` and `test/`, so
#: `stale_test_pins` reads from here while the dead-id audit stays in RUNNER.
REPO_ROOT = os.path.dirname(RUNNER)

TIMEOUT = float(os.environ.get("ORCH_MODEL_AUDIT_TIMEOUT", "20") or 20)

#: Files whose model IDs are routing decisions rather than history. Test files,
#: vendored copies and the runtime scratch tree are excluded: a model name in a
#: test fixture is a fixture, and one in `.runtime/` is a copy of something
#: already audited here.
SKIP_DIRS = (".runtime", "_to_delete", "node_modules", "__pycache__",
             ".git", "tests", "web")

#: Files that name models WITHOUT routing to them. The question this tool asks
#: is "could the fleet send work to an id the vendor no longer serves?" — a
#: benchmark table is answering a different question and must not be repinned.
#:
#: cost_intelligence.MODEL_QUALITY_INDEX records published SWE-bench scores and
#: list prices per model. Its `deepseek-v4-pro-max` entry is a statement about
#: what pro-max scored and cost; the price constants beside it are even named
#: DEEPSEEK_PROMAX_*. Renaming that key to a live id does not fix anything, it
#: attaches one model's measured results to a different model. Learned the hard
#: way on 2026-08-24, by a repin that broke four of its tests.
SKIP_FILES = ("cost_intelligence.py",)
#: Test files. Split out of the old single SKIP_FILE_RE because the two halves
#: were never the same rule: this file itself must be skipped ALWAYS, while test
#: files are skipped by the dead-id audit but are exactly what `stale_test_pins`
#: needs to read.
TEST_FILE_RE = re.compile(r"(^|/)(test_|conftest)|_test\.py$")

#: ...and this file itself, which necessarily contains every vendor prefix it
#: searches for. Without this it reports its own regex source as a dead model id.
MODEL_ID_AUDIT_RE = re.compile(r"(^|/)model_id_audit\.py$")

#: Retained for callers outside this module: the union the two halves used to be.
SKIP_FILE_RE = re.compile(
    r"(^|/)(test_|conftest)|_test\.py$|(^|/)model_id_audit\.py$")

#: Fallback matcher, used ONLY for a file that will not parse. The normal path
#: reads string literals from the AST, where there are no quotes to anchor to
#: and `provider_of` + `is_pinned_api_id` do the deciding; this pattern exists
#: so an unparseable file is still audited rather than silently skipped.
#:
#: Whichever path finds a candidate, the same three shapes match but are NOT
#: pinned API model IDs, and each is excluded by rule rather than by
#: hand-listing exceptions — a checker that cries wolf gets ignored, and then
#: it protects nothing:
#:
#:   "deepseek", "gemini"      the PROVIDER, not a model      -> needs a digit
#:   "gemini-2.0-"             a deprecation PREFIX, matched  -> trailing '-'
#:                             against real ids by startswith
#:   "deepseek-coder-v2"       a local Ollama model, served   -> in the local
#:                             by this machine, not by an API    catalogue
#:
#: The trailing-separator rule is why this does not strip one: a trailing
#: hyphen is the thing that makes it a prefix rather than an id.
PINNED_RE = re.compile(
    r'["\'](?P<id>(?:gemini|gpt|o[134]|deepseek|grok)[a-z0-9.\-]*)["\']',
    re.IGNORECASE)

#: Names this machine serves locally. Populated once, best-effort: if Ollama is
#: unreachable the set is empty and a local model may be reported as a dead API
#: id — noisy, but never the reverse, so a genuinely dead id is never hidden.
_LOCAL_MODELS = None


def local_models():
    global _LOCAL_MODELS
    if _LOCAL_MODELS is not None:
        return _LOCAL_MODELS
    names = set()
    try:
        host = (os.environ.get("OLLAMA_API_BASE") or os.environ.get("OLLAMA_HOST")
                or "http://127.0.0.1:11434").split()[0].rstrip("/")
        with urllib.request.urlopen(host + "/api/tags", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        for m in data.get("models") or []:
            raw = str(m.get("name") or m.get("model") or "").lower()
            if raw:
                names.add(raw)
                names.add(raw.split(":", 1)[0])   # tag-less form
    except Exception:
        pass
    _LOCAL_MODELS = names
    return names


def is_pinned_api_id(raw, model_id):
    """Is this occurrence a real, pinned, hosted-API model id?

    `raw` is the text exactly as it appeared in source, before normalisation —
    the trailing separator that distinguishes a prefix from an id survives only
    there.
    """
    if raw.endswith("-") or raw.endswith("."):
        return False                      # a startswith() prefix, not an id
    if not any(ch.isdigit() for ch in model_id):
        return False                      # bare provider name or internal alias
    if "-" not in model_id and "." not in model_id:
        return False                      # "gpt5" style bare word
    if model_id in local_models():
        return False                      # served by this machine, not a vendor
    return True

#: Which vendor owns an ID prefix.
def provider_of(model_id):
    m = (model_id or "").lower()
    if m.startswith("gemini") or m.startswith("gemma"):
        return "google"
    if m.startswith("gpt") or re.match(r"^o[134]([.\-]|$)", m):
        return "openai"
    if m.startswith("deepseek"):
        return "deepseek"
    if m.startswith("grok"):
        return "xai"
    if m.startswith("claude"):
        return "anthropic"
    return ""


def _load_env():
    for path in (os.path.join(RUNNER, ".env"),
                 os.path.expanduser("~/.claude-orchestrator/.env")):
        try:
            with open(path) as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    os.environ.setdefault(
                        key.strip(),
                        value.split("#")[0].strip().strip('"').strip("'"))
        except OSError:
            continue


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def catalogue_google():
    key = (os.environ.get("GEMINI_API_KEY")
           or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        return None
    out = set()
    url = (f"https://generativelanguage.googleapis.com/v1beta/models"
           f"?key={key}&pageSize=200")
    data = _get(url)
    for m in data.get("models") or []:
        name = str(m.get("name") or "").split("/")[-1]
        # Only models that can actually answer a completion count as live.
        if "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.add(name.lower())
    return out


def catalogue_openai():
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    data = _get("https://api.openai.com/v1/models",
                {"Authorization": f"Bearer {key}"})
    return {str(m.get("id") or "").lower() for m in (data.get("data") or [])}


def catalogue_deepseek():
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return None
    data = _get("https://api.deepseek.com/models",
                {"Authorization": f"Bearer {key}"})
    return {str(m.get("id") or "").lower() for m in (data.get("data") or [])}


def catalogue_xai():
    key = (os.environ.get("GROK_API_KEY")
           or os.environ.get("XAI_API_KEY") or "").strip()
    if not key:
        return None
    data = _get("https://api.x.ai/v1/models",
                {"Authorization": f"Bearer {key}"})
    return {str(m.get("id") or "").lower() for m in (data.get("data") or [])}


CATALOGUES = {
    "google": catalogue_google,
    "openai": catalogue_openai,
    "deepseek": catalogue_deepseek,
    "xai": catalogue_xai,
}


def google_serves(model_id):
    """Will Google actually answer for this id? True / False / None (unknown).

    THE CATALOGUE OVER-REPORTS. `gemini-2.5-pro` is listed by ListModels with
    generateContent among its supported methods, and returns

        404 — "This model models/gemini-2.5-pro is no longer available to new
        users. Please update your code to use models/gemini-3.1-pro-preview"

    on the first real call. Same for `gemini-2.5-flash-lite`. Listing is a
    statement about the model; serving is a statement about the model AND this
    key. Only the second one matters to a fleet that has to route work.

    The probe costs nothing to run on a broke account, which is exactly when
    this audit matters most, because the two failures are distinguishable by
    status code before any billing happens:

        429  the account is out of credit  -> the id is FINE, the wallet is not
        404  the id is gone                -> repin it

    So a depleted key still answers the question this tool asks.
    """
    key = (os.environ.get("GEMINI_API_KEY")
           or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model_id}:generateContent?key={key}")
    body = json.dumps({"contents": [{"parts": [{"text": "ok"}]}]}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            resp.read(64)
        return True                       # 200: serving
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False                  # gone
        if exc.code in (429, 402, 403):
            return True                   # billing, not identity
        return None
    except Exception:
        return None


#: Providers whose catalogue is known to over-report, and how to check for real.
SERVES = {"google": google_serves}


def _docstring_nodes(tree):
    """Every string Constant that is a docstring, by identity.

    A model id inside a docstring is documentation, not a routing decision:
    `parallel_provider.run()` documents its argument shape with
    `["claude-opus", "gpt-4o", "gemini-2.0"]`, and repinning prose would be
    both pointless and wrong. Line-based scanning cannot tell the difference —
    a docstring line looks like any other line. Python's own parser can.
    """
    out = set()
    import ast
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(id(body[0].value))
    return out


def scan(root=None, tests=False):
    """{model_id: {"path:line", ...}} for every pinned ID under `root`.

    Reads string literals through the AST rather than by regex over lines, so
    comments and docstrings are excluded by construction instead of by a
    heuristic. Falls back to a line scan only for a file that will not parse.

    `tests=True` inverts the file filter and scans ONLY the test files the
    normal path skips. That result is never repinned — see `stale_test_pins`
    for the one question it is used to answer.
    """
    import ast
    root = root or RUNNER
    found = {}

    def record(mid, rel, lineno):
        found.setdefault(mid, set()).add(f"{rel}:{lineno}")

    def consider(raw, rel, lineno):
        text = str(raw).lower()
        # The fleet writes a model three ways and they all name the same thing:
        #   "gemini-3.5-flash"           bare
        #   "google:gemini-3.5-flash"    provider-qualified (routing tables)
        #   "gemini/gemini-3.5-flash"    aider's --model form
        # Only the model half is the vendor's identifier; auditing the whole
        # string would report every qualified reference as an unknown id.
        for sep in (":", "/"):
            if sep in text:
                text = text.rsplit(sep, 1)[1]
        mid = text.rstrip("-.")
        if not provider_of(mid):
            return
        if not is_pinned_api_id(text, mid):
            return
        record(mid, rel, lineno)

    skip_dirs = SKIP_DIRS
    if tests:
        skip_dirs = tuple(d for d in SKIP_DIRS if d != "tests")

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            if name in SKIP_FILES or MODEL_ID_AUDIT_RE.search(rel):
                continue
            if bool(TEST_FILE_RE.search(rel)) != tests:
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    source = fh.read()
            except OSError:
                continue
            try:
                tree = ast.parse(source, filename=path)
            except SyntaxError:
                # Unparseable (a py2 relic, a template). Fall back to lines so
                # the file is still audited, accepting the docstring noise.
                for lineno, line in enumerate(source.splitlines(), 1):
                    if line.lstrip().startswith("#"):
                        continue
                    for m in PINNED_RE.finditer(line):
                        consider(m.group("id"), rel, lineno)
                continue
            skip = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                if not isinstance(node.value, str) or id(node) in skip:
                    continue
                consider(node.value, rel, getattr(node, "lineno", 0))
    return found


def stale_test_pins(root=None):
    """{model_id: {"path:line", ...}} for ids pinned ONLY by tests.

    A different question from the rest of this file, and an offline one. The
    audit above asks the vendor "do you still serve this?". This asks the tree
    "does any routing code still name this?" — and the answer is the tell for a
    test whose expectation went stale when source got repinned underneath it.

    The failure it exists to catch, concretely: 45afe205 repinned twelve dead
    ids and deliberately left tests alone, on the sound reasoning that a test
    naming a dead model usually pins it on purpose. True for
    test_provider_banner_exhaustion.py, which pins verbatim 404 text as
    evidence. Not true for tests/test_routing.py, which hardcoded the DEFAULT
    VALUE of PREFLIGHT_ESCALATED_MODEL in eight assertions and went red the
    moment the constant moved 2.0-flash -> 2.5-flash. Nothing caught it,
    because the audit does not read tests and the vendor catalogue has no
    opinion about what a test expects.

    Narrowed to ids with a SIBLING still in source — same family, different
    version — because that is the fingerprint of a repin and the unnarrowed
    answer is useless. Scanning every test-only id reports 31 on this tree,
    almost all obvious fixtures: `claude-9912`, `claude using author model
    claude-sonnet-4-6`, synthetic names invented by a test. This file already
    knows what that costs — "a checker that cries wolf gets ignored, and then
    it protects nothing" — so the family rule is the same kind of exclusion by
    rule, not by hand-listed exception. A test naming `gemini-2.0-flash` while
    source routes to `gemini-2.5-flash` is a question worth asking; a test
    naming an id no source id even rhymes with is a fixture.

    Reporting only. These are never repinned automatically: whether a lone id
    is a stale expectation or a deliberately-pinned relic is a judgement about
    what the test is FOR, and this tool cannot make it. It can only put the
    short list of candidates in front of someone who can — which beats
    discovering them one red suite at a time.

    Source is read from the runner, tests from the whole repo, and the two
    roots are deliberately different. Routing lives in `runner/`, which is why
    the audit above scopes there — but tests do not: this fleet has suites in
    `tests/`, `runner/tests/`, `beethoven/tests/` and `test/`, and the file
    that actually went stale (`tests/test_routing.py`) is at the repo root.
    Scoping both sides to the runner would have missed it, which is the whole
    point of the function.
    """
    source_root = root or RUNNER
    test_root = root or REPO_ROOT
    source_ids = set(scan(source_root))
    source_families = {_family(mid) for mid in source_ids}
    source_families.discard("")
    return {mid: sites for mid, sites in scan(test_root, tests=True).items()
            if mid not in source_ids and _family(mid) in source_families}


def _family(model_id):
    """`gemini-2.0-flash` and `gemini-2.5-flash` -> `gemini-flash`.

    Version-bearing tokens are dropped, which is what makes two ids siblings.
    Splitting on '-' only (not '.') keeps `claude-haiku-4.5` and
    `claude-haiku-4-5-20251001` in the same family, which they are: the fleet
    writes the same model both ways.
    """
    kept = [tok for tok in str(model_id).split("-")
            if tok and not any(ch.isdigit() for ch in tok)]
    return "-".join(kept)


def audit(root=None):
    """(dead, live, unverifiable, errors)."""
    pinned = scan(root)
    by_provider = {}
    for mid in pinned:
        by_provider.setdefault(provider_of(mid), set()).add(mid)

    catalogues, errors = {}, {}
    for provider in sorted(by_provider):
        if provider == "anthropic":
            continue
        fetch = CATALOGUES.get(provider)
        if not fetch:
            errors[provider] = "no catalogue endpoint known"
            continue
        try:
            got = fetch()
        except urllib.error.HTTPError as exc:
            errors[provider] = f"HTTP {exc.code}"
            continue
        except Exception as exc:
            errors[provider] = f"{type(exc).__name__}: {exc}"
            continue
        if got is None:
            errors[provider] = "no key configured"
        else:
            catalogues[provider] = got

    dead, live, unverifiable = {}, {}, {}
    for mid, sites in pinned.items():
        provider = provider_of(mid)
        cat = catalogues.get(provider)
        if cat is None:
            unverifiable[mid] = sites
        elif mid in cat:
            # Listed. For a provider whose catalogue over-reports, ask whether
            # it will actually serve this id before calling it live.
            probe = SERVES.get(provider)
            verdict = probe(mid) if probe else True
            if verdict is False:
                dead[mid] = sites
            elif verdict is None:
                unverifiable[mid] = sites
            else:
                live[mid] = sites
        else:
            dead[mid] = sites
    return dead, live, unverifiable, errors


def _report_stale_test_pins(argv):
    """`--stale-test-pins`: offline, no catalogue, no network."""
    stale = stale_test_pins()
    if "--json" in argv:
        print(json.dumps({"stale_test_pins": {k: sorted(v)
                                              for k, v in stale.items()}},
                         indent=2, sort_keys=True))
        return 0
    if not stale:
        print("model_id_audit: no test pins a model id that source has dropped.")
        return 0
    print(f"model_id_audit: {len(stale)} model id(s) pinned only by tests.\n")
    print("  Each is named by a test and by no routing code. That is either a")
    print("  deliberate relic (a 404 fixture, a historical banner) or a stale")
    print("  expectation left behind by a repin. Read the test and decide —")
    print("  this tool does not repin them.\n")
    for mid in sorted(stale):
        sites = sorted(stale[mid])
        print(f"    {mid}")
        for site in sites[:6]:
            print(f"        {site}")
        if len(sites) > 6:
            print(f"        … and {len(sites) - 6} more")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--stale-test-pins" in argv:
        return _report_stale_test_pins(argv)
    _load_env()
    dead, live, unverifiable, errors = audit()

    if "--json" in argv:
        print(json.dumps({
            "dead": {k: sorted(v) for k, v in dead.items()},
            "live": sorted(live),
            "unverifiable": sorted(unverifiable),
            "errors": errors,
        }, indent=2, sort_keys=True))
        return 1 if dead else (2 if errors and not live else 0)

    print(f"model_id_audit: {len(dead) + len(live) + len(unverifiable)} pinned "
          f"model id(s) across the runner")
    for provider, why in sorted(errors.items()):
        print(f"  catalogue unavailable — {provider}: {why}")

    if dead:
        print(f"\n  DEAD — the vendor no longer serves these ({len(dead)}):")
        for mid in sorted(dead):
            sites = sorted(dead[mid])
            print(f"    {mid}")
            for site in sites[:6]:
                print(f"        {site}")
            if len(sites) > 6:
                print(f"        … and {len(sites) - 6} more")

    if unverifiable:
        print(f"\n  UNVERIFIED — no catalogue to check against ({len(unverifiable)}):")
        print("    " + ", ".join(sorted(unverifiable)))

    if "--list" in argv and live:
        print(f"\n  LIVE ({len(live)}):")
        print("    " + ", ".join(sorted(live)))

    if dead:
        print(f"\n{len(dead)} pinned model id(s) are gone. A task routed to one of "
              "these fails\nwith a 404 that reads like any other provider error. "
              "Repin them.")
        return 1
    if not live and errors:
        print("\nCould not verify anything — treating that as unknown, not as OK.")
        return 2
    print(f"\nAll {len(live)} verifiable pinned model id(s) are live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
