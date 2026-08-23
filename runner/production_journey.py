#!/usr/bin/env python3
"""
production_journey.py — task-defined production journeys and their receipts.

WHY
---
`deployment_terminal.verify_release()` promoted work on two facts: the production URL
returned HTTP 200 and the release SHA was live. Both are necessary. Neither says the
*changed behaviour* works. A 200 from an unchanged cached shell, a marketing page, or a
health stub promoted every attributed task in the release. "The deploy happened" was
being read as "the thing the task claimed to do now works in production."

WHAT THIS ADDS
--------------
1. Every task (or fused release) declares a BOUNDED journey appropriate to its change.
   A journey is a short, explicit list of probe steps with assertions. Bounded means
   capped step count, per-step timeout and a total wall-clock budget — a journey can
   never become an open-ended crawl.
2. Non-web changes declare an ALTERNATE probe (`command`, `artifact`, or an explicitly
   justified `none`) so "this change has no URL" cannot silently become "no evidence
   required".
3. Journeys run AFTER deployment against the real release SHA, with retry/backoff, and
   produce a structured, REDACTED receipt: url, environment, sha, steps, assertions,
   timings, attempts, verdict.
4. Verdicts are pass / fail / flaky. Flaky is its own verdict — a step that only passed
   on retry is not a pass, and by default does not promote.
5. Promotion consumes receipts: `gate()` answers "may this task be promoted?" and
   returns HTTP-200-alone as an explicit refusal reason.

ENV FLAGS
---------
  ORCH_JOURNEY_ENABLED        default ON  — run journeys and require them for promotion
  ORCH_JOURNEY_ALLOW_FLAKY    default OFF — treat a flaky verdict as a pass
  ORCH_JOURNEY_MAX_STEPS      default 8
  ORCH_JOURNEY_STEP_TIMEOUT   default 20  (seconds)
  ORCH_JOURNEY_BUDGET_S       default 120 (seconds, whole journey)
  ORCH_JOURNEY_RETRIES        default 2   (extra attempts per step)
  ORCH_JOURNEY_BACKOFF_S      default 1.0 (base of exponential backoff)
  ORCH_JOURNEY_MAX_BODY       default 2000000 (bytes of response body read per step)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------------- verdicts

PASS = "pass"
FAIL = "fail"
FLAKY = "flaky"
SKIPPED = "skipped"

# A journey that was never declared or never ran. Distinct from FAIL: nothing proved it
# broken, but nothing proved it worked either, and that must not promote.
MISSING = "missing"

PROBE_HTTP = "http"
PROBE_COMMAND = "command"
PROBE_ARTIFACT = "artifact"
PROBE_NONE = "none"
PROBE_KINDS = (PROBE_HTTP, PROBE_COMMAND, PROBE_ARTIFACT, PROBE_NONE)

_TRUTHY = ("1", "true", "yes", "on")


def _on(flag, default="1"):
    return os.environ.get(flag, default).strip().lower() in _TRUTHY


def _int_env(flag, default):
    try:
        return int(os.environ.get(flag, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(flag, default):
    try:
        return float(os.environ.get(flag, str(default)))
    except (TypeError, ValueError):
        return default


def max_steps():
    return max(1, _int_env("ORCH_JOURNEY_MAX_STEPS", 8))


def step_timeout():
    return max(1, _int_env("ORCH_JOURNEY_STEP_TIMEOUT", 20))


def budget_seconds():
    # Float so sub-second budgets are expressible (tests, and very tight probes).
    return max(0.01, _float_env("ORCH_JOURNEY_BUDGET_S", 120))


def retries():
    return max(0, _int_env("ORCH_JOURNEY_RETRIES", 2))


def backoff_seconds():
    return max(0.0, _float_env("ORCH_JOURNEY_BACKOFF_S", 1.0))


def max_body_bytes():
    """How much of a response body an assertion may be evaluated against.

    This is a bound, not a preference: an unbounded read turns a probe into a
    memory hazard against a hostile or broken origin. But the bound has to be
    larger than the pages being asserted on. It was 200_000 and apparently.cc's
    /pricing is 667_737 bytes of server-rendered HTML with the Nuxt payload
    inlined, so every assertion about the second half of that page was evaluated
    against bytes that were never read.
    """
    return max(1024, _int_env("ORCH_JOURNEY_MAX_BODY", 2_000_000))


# -------------------------------------------------------------------- redaction

# Receipts are persisted and served over the proof UI, so they are scrubbed before
# storage, not before display. Anything that looks like a credential never lands.
_REDACTIONS = (
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]+"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b(sk|pk|ghp|gho|ghs|github_pat|xox[abprs])[-_][A-Za-z0-9_\-]{8,}"), "[REDACTED]"),
    (re.compile(r"(?i)([?&](?:token|key|secret|password|passwd|pwd|api[_-]?key|access[_-]?token|"
                r"auth|signature|sig)=)[^&#\s]+"), r"\1[REDACTED]"),
    # `&` is excluded from the value class so scrubbing one query parameter cannot
    # swallow the harmless ones that follow it.
    (re.compile(r"(?i)\b([A-Za-z0-9_]*(?:token|secret|password|api[_-]?key)[A-Za-z0-9_]*)"
                r"(\s*[:=]\s*)(\"?)[^\s\"',&]{4,}"), r"\1\2\3[REDACTED]"),
    (re.compile(r"https?://[^/\s:@]+:[^/\s@]+@"), "https://[REDACTED]@"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED-EMAIL]"),
)

_MAX_DETAIL = 600


def redact(value):
    """Recursively scrub credential-shaped substrings out of a receipt fragment."""
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    out = value
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out[:_MAX_DETAIL]


# ---------------------------------------------------------------- journey specs


class JourneySpecError(ValueError):
    """A declared journey is malformed or exceeds its bounds."""


def _as_steps(raw):
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [s for s in raw if isinstance(s, dict)]
    raise JourneySpecError(f"steps must be a list of dicts, got {type(raw).__name__}")


def parse_spec(raw, *, slug="", environment="production"):
    """Normalise a declared journey into a bounded, validated spec.

    `raw` may be a dict or a JSON string (that is how tasks carry it in the DB).
    """
    if raw in (None, "", {}, []):
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as e:
            raise JourneySpecError(f"journey is not valid JSON: {e}")
    if not isinstance(raw, dict):
        raise JourneySpecError("journey must be an object")

    kind = str(raw.get("probe") or raw.get("kind") or PROBE_HTTP).lower()
    if kind not in PROBE_KINDS:
        raise JourneySpecError(f"unknown probe kind {kind!r}; expected one of {PROBE_KINDS}")

    steps = _as_steps(raw.get("steps"))
    if kind == PROBE_NONE:
        justification = str(raw.get("justification") or "").strip()
        if len(justification) < 12:
            # An unjustified opt-out is the exact hole this task exists to close.
            raise JourneySpecError("probe 'none' requires a justification of >= 12 chars")
        steps = []
    elif not steps:
        raise JourneySpecError(f"probe {kind!r} declares no steps")

    if len(steps) > max_steps():
        raise JourneySpecError(f"journey declares {len(steps)} steps; bound is {max_steps()}")

    normalised = []
    for i, step in enumerate(steps):
        s = dict(step)
        s.setdefault("name", f"step-{i + 1}")
        s.setdefault("probe", kind)
        s["probe"] = str(s["probe"]).lower()
        if s["probe"] not in PROBE_KINDS:
            raise JourneySpecError(f"step {s['name']}: unknown probe {s['probe']!r}")
        if s["probe"] == PROBE_HTTP:
            s.setdefault("path", "/")
            s.setdefault("expect_status", 200)
            if not _assertions_of(s):
                # An http step whose only assertion is status 200 is the failure mode
                # this module was written to eliminate.
                raise JourneySpecError(
                    f"step {s['name']}: an http step must assert something beyond "
                    "expect_status (expect_body_contains / expect_body_absent / expect_header)")
        elif s["probe"] == PROBE_COMMAND:
            if not s.get("command"):
                raise JourneySpecError(f"step {s['name']}: command probe needs a 'command'")
            s.setdefault("expect_exit", 0)
        elif s["probe"] == PROBE_ARTIFACT:
            if not s.get("path"):
                raise JourneySpecError(f"step {s['name']}: artifact probe needs a 'path'")
        s["timeout_s"] = min(int(s.get("timeout_s") or step_timeout()), step_timeout())
        normalised.append(s)

    return {
        "slug": slug or str(raw.get("slug") or ""),
        "probe": kind,
        "environment": str(raw.get("environment") or environment),
        "required": bool(raw.get("required", True)),
        "justification": str(raw.get("justification") or ""),
        "steps": normalised,
    }


def _assertions_of(step):
    """Assertions declared by an http step, beyond the bare status code."""
    out = []
    if step.get("expect_body_contains"):
        out.append(("body_contains", step["expect_body_contains"]))
    if step.get("expect_body_absent"):
        out.append(("body_absent", step["expect_body_absent"]))
    if step.get("expect_header"):
        out.append(("header", step["expect_header"]))
    return out


def spec_for_task(task, *, environment="production"):
    """The journey a task declares, or None. Never invents one."""
    task = task or {}
    raw = task.get("journey") or task.get("production_journey")
    if not raw:
        return None
    return parse_spec(raw, slug=str(task.get("slug") or ""), environment=environment)


# --------------------------------------------------------------------- probing


class _Headers(dict):
    """Response headers with case-insensitive lookup, plus a truncation flag.

    urllib returns an email.message.Message whose keys are canonical-cased
    ("Content-Type"). dict(...) of it keeps that casing and loses the
    case-insensitive lookup HTTP requires, so `headers.get("content-type")`
    returned None for every response ever probed and EVERY expect_header
    assertion failed with actual=None. Nothing caught it because no journey had
    ever run against a real origin.

    Test doubles inject plain dicts; those keep plain-dict behaviour and report
    .truncated as False via getattr's default.
    """

    truncated = False

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return dict.get(self, key)
        want = str(key).lower()
        for k, v in self.items():
            if str(k).lower() == want:
                return v
        return default


def _default_http(url, timeout=20, headers=None):
    """Plain GET returning (status, body, headers). Injectable for tests."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers=dict(
        {"User-Agent": "beethoven-production-journey/1.0"}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cap = max_body_bytes()
            # One byte past the cap, so truncation is detected rather than assumed.
            raw = r.read(cap + 1)
            h = _Headers(r.headers)
            h.truncated = len(raw) > cap
            return r.status, raw[:cap].decode("utf-8", "replace"), h
    except urllib.error.HTTPError as e:
        cap = max_body_bytes()
        try:
            raw = e.read(cap + 1)
        except Exception:
            raw = b""
        h = _Headers(getattr(e, "headers", {}) or {})
        h.truncated = len(raw) > cap
        return e.code, raw[:cap].decode("utf-8", "replace"), h
    except Exception as e:
        return None, f"transport error: {e}", {}


def _default_command(command, timeout=20, cwd=None):
    """Bounded command probe. argv list only — never a shell string."""
    if isinstance(command, str):
        raise JourneySpecError("command probe must be an argv list, not a shell string")
    proc = subprocess.run(list(command), capture_output=True, text=True,
                          timeout=timeout, cwd=cwd or None)
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))[-4000:]


def _join(base_url, path):
    if not path or path == "/":
        return base_url.rstrip("/") + "/"
    if str(path).startswith("http"):
        return path
    return base_url.rstrip("/") + "/" + str(path).lstrip("/")


def _run_http_step(step, base_url, http):
    url = _join(base_url or "", step.get("path") or "/")
    status, body, headers = http(url, timeout=step["timeout_s"])
    body = body or ""
    assertions = [{"name": "status", "expected": step.get("expect_status", 200),
                   "actual": status, "ok": status == step.get("expect_status", 200)}]
    # A body we only partly read cannot answer "is this string absent?". Reporting
    # unproven as absent is how a truncated error page promotes as a clean one — the
    # exact substitution this module exists to refuse.
    cut = bool(getattr(headers, "truncated", False))
    inconclusive = f"inconclusive: response body truncated at {len(body)} bytes"
    for name, expected in _assertions_of(step):
        if name == "body_contains":
            ok = all(str(x) in body for x in _listify(expected))
            actual = "present" if ok else (inconclusive if cut else "absent")
        elif name == "body_absent":
            ok = all(str(x) not in body for x in _listify(expected))
            if not ok:
                actual = "present"
            elif cut:
                ok, actual = False, inconclusive
            else:
                actual = "absent"
        else:  # header
            hdr, want = (list(expected.items())[0] if isinstance(expected, dict)
                         else (str(expected), None))
            got = headers.get(hdr) or headers.get(str(hdr).lower())
            ok = bool(got) if want is None else (str(want).lower() in str(got or "").lower())
            actual = got
        assertions.append({"name": name, "expected": expected, "actual": actual, "ok": bool(ok)})
    return assertions, url, f"status={status} bytes={len(body)}"


def _listify(value):
    return value if isinstance(value, (list, tuple)) else [value]


def _run_command_step(step, runner):
    code, output = runner(step["command"], timeout=step["timeout_s"], cwd=step.get("cwd"))
    assertions = [{"name": "exit_code", "expected": step.get("expect_exit", 0),
                   "actual": code, "ok": code == step.get("expect_exit", 0)}]
    if step.get("expect_output_contains"):
        ok = all(str(x) in output for x in _listify(step["expect_output_contains"]))
        assertions.append({"name": "output_contains", "expected": step["expect_output_contains"],
                           "actual": "present" if ok else "absent", "ok": ok})
    return assertions, " ".join(map(str, step["command"]))[:200], output[-400:]


def _run_artifact_step(step):
    path = step["path"]
    exists = os.path.exists(path)
    assertions = [{"name": "artifact_exists", "expected": True, "actual": exists, "ok": exists}]
    if exists and step.get("min_bytes"):
        size = os.path.getsize(path)
        assertions.append({"name": "min_bytes", "expected": step["min_bytes"],
                           "actual": size, "ok": size >= int(step["min_bytes"])})
    return assertions, path, ("present" if exists else "missing")


# ----------------------------------------------------------------- the journey


def run_journey(spec, *, base_url="", sha="", environment=None, http=None, command=None,
                sleep=None, clock=None):
    """Execute a bounded journey and return a structured, redacted receipt.

    Injectable `http`, `command`, `sleep` and `clock` keep this deterministic in tests.
    """
    if spec is None:
        return receipt_missing(sha=sha, base_url=base_url, environment=environment,
                               reason="no journey declared")
    http = http or _default_http
    command = command or _default_command
    sleep = sleep if sleep is not None else time.sleep
    clock = clock or time.monotonic

    started = clock()
    budget = budget_seconds()
    max_attempts = retries() + 1
    steps_out = []
    verdict = PASS

    if spec["probe"] == PROBE_NONE:
        return _finalise(spec, [], PASS, sha, base_url, environment, 0,
                         note=f"alternate probe 'none': {spec['justification']}")

    for step in spec["steps"]:
        elapsed = clock() - started
        if elapsed >= budget:
            steps_out.append({"name": step["name"], "probe": step["probe"], "verdict": SKIPPED,
                              "attempts": 0, "duration_ms": 0, "assertions": [],
                              "detail": f"journey budget {budget}s exhausted after {elapsed:.1f}s"})
            verdict = FAIL
            continue

        attempts, step_verdict, assertions, target, detail = 0, FAIL, [], "", ""
        step_started = clock()
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            try:
                if step["probe"] == PROBE_HTTP:
                    assertions, target, detail = _run_http_step(step, base_url, http)
                elif step["probe"] == PROBE_COMMAND:
                    assertions, target, detail = _run_command_step(step, command)
                else:
                    assertions, target, detail = _run_artifact_step(step)
            except Exception as e:                       # a probe crash is a failed probe
                assertions = [{"name": "probe_error", "expected": "no exception",
                               "actual": str(e), "ok": False}]
                target, detail = target or "", f"probe raised {type(e).__name__}: {e}"
            if all(a["ok"] for a in assertions):
                # Passing only after a retry is NOT a clean pass: production was
                # observed in two different states inside one journey.
                step_verdict = PASS if attempt == 1 else FLAKY
                break
            if attempt < max_attempts:
                sleep(backoff_seconds() * (2 ** (attempt - 1)))
            if clock() - started >= budget:
                detail = (detail + " | budget exhausted mid-retry").strip(" |")
                break

        steps_out.append({
            "name": step["name"], "probe": step["probe"], "verdict": step_verdict,
            "attempts": attempts, "duration_ms": int(max(0.0, clock() - step_started) * 1000),
            "target": target, "assertions": assertions, "detail": detail,
        })
        if step_verdict == FAIL:
            verdict = FAIL
        elif step_verdict == FLAKY and verdict == PASS:
            verdict = FLAKY

    total_ms = int(max(0.0, clock() - started) * 1000)
    return _finalise(spec, steps_out, verdict, sha, base_url, environment, total_ms)


def _finalise(spec, steps, verdict, sha, base_url, environment, total_ms, note=""):
    receipt = {
        "schema": 1,
        "slug": spec.get("slug", ""),
        "probe": spec.get("probe"),
        "required": bool(spec.get("required", True)),
        "environment": str(environment or spec.get("environment") or "production"),
        "url": base_url or "",
        "sha": str(sha or ""),
        "verdict": verdict,
        "steps": steps,
        "assertion_count": sum(len(s.get("assertions") or []) for s in steps),
        "failed_assertions": [
            {"step": s["name"], "assertion": a["name"], "expected": a["expected"], "actual": a["actual"]}
            for s in steps for a in (s.get("assertions") or []) if not a["ok"]
        ],
        "duration_ms": total_ms,
        "note": note,
        "recorded_at": time.time(),
    }
    receipt = redact(receipt)
    receipt["id"] = hashlib.sha256(json.dumps(
        {k: v for k, v in receipt.items() if k != "recorded_at"},
        sort_keys=True, default=str).encode()).hexdigest()[:32]
    return receipt


def receipt_missing(*, sha="", base_url="", environment=None, reason="no journey declared",
                    slug=""):
    """The explicit 'nothing proved this' receipt. Never promotes."""
    return _finalise({"slug": slug, "probe": PROBE_NONE, "required": True,
                      "environment": environment, "justification": ""},
                     [], MISSING, sha, base_url, environment, 0, note=reason)


# ------------------------------------------------------------------- the gate


HTTP_200_ONLY_REASON = (
    "release health (HTTP 200 + live SHA) is necessary but not sufficient: "
    "no passing production journey receipt for this task")


def gate(receipt, *, required=True):
    """(ok, reason). The single place promotion asks 'did the journey prove it?'"""
    if not _on("ORCH_JOURNEY_ENABLED"):
        return True, "journeys disabled (ORCH_JOURNEY_ENABLED=0)"
    if not receipt:
        return (False, HTTP_200_ONLY_REASON) if required else (True, "no journey required")
    verdict = receipt.get("verdict")
    if verdict == PASS:
        return True, "journey passed"
    if verdict == FLAKY:
        if _on("ORCH_JOURNEY_ALLOW_FLAKY", "0"):
            return True, "journey flaky (allowed by ORCH_JOURNEY_ALLOW_FLAKY)"
        return False, ("journey flaky: production was observed in two states within one "
                       "run; a retry-only pass is not delivery")
    if verdict == MISSING:
        return (False, HTTP_200_ONLY_REASON) if (required or receipt.get("required")) \
            else (True, "no journey required")
    failed = receipt.get("failed_assertions") or []
    first = failed[0] if failed else {}
    return False, ("journey failed: " + (
        f"{first.get('step')}/{first.get('assertion')} expected={first.get('expected')!r} "
        f"actual={first.get('actual')!r}" if first else "no passing steps"))


def should_roll_back(receipt):
    """A required journey that FAILED after deployment is a bad release, not a bad task.

    Flaky and missing do not trigger rollback: neither is evidence that production is
    broken, only that it is unproven. Rolling back on unproven would make the fleet
    thrash on its own instrumentation gaps.
    """
    if not receipt or not _on("ORCH_JOURNEY_ENABLED"):
        return False
    return bool(receipt.get("required", True)) and receipt.get("verdict") == FAIL


# ------------------------------------------------------------------- receipts


def _dir():
    home = os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(__file__), "..", ".runtime"))
    path = os.path.join(home, "journey-receipts")
    os.makedirs(path, exist_ok=True)
    return path


def _publish(receipt):
    """Mirror a receipt into public.shipped_metrics, where readers look for it.

    WHY THIS EXISTS.

    store() wrote receipts to .runtime/journey-receipts/ and nowhere else. Those
    files are host-local: invisible to every other runner, to the web UI, and —
    critically — to canonical_proof_ledger, which reads its journey evidence from
    the `shipped_metrics` TABLE.

    So the producer wrote files and the only consumer read a table, and the two
    never met. DEPLOYED_AND_VERIFIED requires an exact live release SHA AND a
    passing journey receipt; releases were healthy the whole time, and the second
    half could never be satisfied. Nothing was marked verified for sixteen days.

    Fail-soft on purpose. The file on disk is the durable record; this is the
    copy the fleet can see. If the control plane is unreachable, the receipt is
    still written locally and can be backfilled — losing the mirror must never
    lose the evidence.
    """
    try:
        import db
    except Exception:
        return False
    try:
        verdict = str(receipt.get("verdict") or "").lower()
        recorded = receipt.get("recorded_at")
        try:
            from datetime import datetime, timezone
            recorded_iso = datetime.fromtimestamp(float(recorded), timezone.utc).isoformat()
        except Exception:
            recorded_iso = None
        row = {
            "id": receipt.get("id"),
            "slug": receipt.get("slug"),
            "release_sha": receipt.get("sha"),
            # The ledger matches a task's required journey by name. Fall back to
            # the probe kind so a receipt is never keyed on an empty string.
            "journey": receipt.get("journey") or receipt.get("probe") or "default",
            "ok": verdict == PASS,
            "verdict": verdict or None,
            "url": receipt.get("url"),
            "environment": receipt.get("environment"),
            "required": bool(receipt.get("required")),
            "detail": {
                "assertion_count": receipt.get("assertion_count"),
                "duration_ms": receipt.get("duration_ms"),
                "failed_assertions": receipt.get("failed_assertions") or [],
                "note": receipt.get("note"),
            },
        }
        if recorded_iso:
            row["recorded_at"] = recorded_iso
        if not row["id"] or not row["release_sha"]:
            return False
        db.upsert("shipped_metrics", row)
        return True
    except Exception as exc:
        print(f"[production_journey] receipt mirror failed (kept on disk): {exc}", flush=True)
        return False


def store(receipt):
    """Persist a receipt atomically. Returns its path. Already redacted by _finalise."""
    path = os.path.join(_dir(), f"{receipt['id']}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, sort_keys=True, default=str)
    os.replace(tmp, path)
    # Disk first, then publish. A receipt that exists only in the database is one
    # an unreachable control plane can lose; a receipt that exists only on disk is
    # one no consumer can read. It needs to be in both.
    _publish(receipt)
    return path


def load_all(limit=100, sha=None, slug=None):
    """Recent receipts, newest first, optionally filtered by release sha or task slug."""
    out = []
    try:
        names = os.listdir(_dir())
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(_dir(), name), encoding="utf-8") as f:
                receipt = json.load(f)
        except (OSError, ValueError):
            continue
        if sha and not str(receipt.get("sha", "")).startswith(str(sha)[:12]):
            continue
        if slug and receipt.get("slug") != slug:
            continue
        out.append(receipt)
    out.sort(key=lambda r: r.get("recorded_at") or 0, reverse=True)
    return out[:limit]


def find(sha, slug):
    """The most recent receipt for (release sha, task slug), or None."""
    found = load_all(limit=1, sha=sha, slug=slug)
    return found[0] if found else None


def summary(limit=50):
    """Compact roll-up for the proof UI."""
    receipts = load_all(limit=limit)
    counts = {PASS: 0, FAIL: 0, FLAKY: 0, MISSING: 0}
    for r in receipts:
        counts[r.get("verdict", MISSING)] = counts.get(r.get("verdict", MISSING), 0) + 1
    return {
        "total": len(receipts),
        "verdicts": counts,
        "recent": [{"slug": r.get("slug"), "verdict": r.get("verdict"), "sha": (r.get("sha") or "")[:12],
                    "environment": r.get("environment"), "url": r.get("url"),
                    "assertions": r.get("assertion_count"), "duration_ms": r.get("duration_ms"),
                    "failed": r.get("failed_assertions") or []}
                   for r in receipts[:20]],
    }


def verify_task(task, *, base_url="", sha="", environment="production", store_receipt=True, **kw):
    """Run a task's declared journey after deployment and return its receipt.

    A task with no declared journey gets an explicit MISSING receipt so the absence is
    recorded rather than inferred.
    """
    try:
        spec = spec_for_task(task, environment=environment)
    except JourneySpecError as e:
        receipt = receipt_missing(sha=sha, base_url=base_url, environment=environment,
                                  slug=str((task or {}).get("slug") or ""),
                                  reason=f"invalid journey spec: {e}")
        if store_receipt:
            store(receipt)
        return receipt
    if spec is None:
        receipt = receipt_missing(sha=sha, base_url=base_url, environment=environment,
                                  slug=str((task or {}).get("slug") or ""))
    else:
        receipt = run_journey(spec, base_url=base_url, sha=sha, environment=environment, **kw)
    if store_receipt:
        try:
            store(receipt)
        except OSError:
            pass
    return receipt


if __name__ == "__main__":
    print(json.dumps(summary(), indent=2, default=str))
