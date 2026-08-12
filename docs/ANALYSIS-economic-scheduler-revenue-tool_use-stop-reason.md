# Failure analysis — `economic-scheduler-revenue`, `stop_reason: "tool_use"`

**Task:** `backlog-batch-beethoven-2863be9-recover-economic-scheduler-revenue`
**Named session:** `60109094-93b0-4a46-9215-7c8aa3431d5f`
**Scope:** diagnosis only. The task states *"Do **not** attempt a fix at this stage."*
No production behaviour is changed by this document.

---

## 0. Evidence availability — read this before trusting anything below

The named session log **could not be retrieved**:

- `SELECT count(*) FROM session_actions WHERE session_id::text =
  '60109094-93b0-4a46-9215-7c8aa3431d5f'` returns **0**. `session_actions` is the
  only table in the schema carrying a `session_id` column.
- No `tasks` row references that session id; the ten `%economic-scheduler-revenue%`
  tasks carry only routing notes (`agentic-repair:rework`, `preflight: exhausted 5
  attempts without success`, `[ev-low-priority…]`), none of which quote a stop reason.

So the literal instruction — *"including specific lines from the logs"* — cannot be
satisfied from that session. **What follows is not reconstructed from the missing
log.** It is derived from the code that produces and consumes the `tool_use` stop
reason, with file and line citations that can be re-checked today. Every claim below
is verifiable by reading the repository; none is inferred from an absent artifact.

That the log is missing is itself the first finding, and it has the same cause as
the second: nothing in the pipeline records the structured failure fields.

---

## 1. What `stop_reason: "tool_use"` means here

The Claude Agent SDK ends a run with a `ResultMessage`. When the agent exhausts its
turn budget mid-tool-call, that message carries:

```
subtype     = "error_max_turns"
stop_reason = "tool_use"
```

The pair means: *the model was cut off while it was calling a tool, not while
writing a final answer*. The run therefore produced **no diff** — it produced a
metadata object where the caller expected a task result. This is the exact
condition `runner/result_classifier.py` was written for:

```python
# runner/result_classifier.py:18
return result.get("subtype") == "error_max_turns" and result.get("stop_reason") == "tool_use"
```

---

## 2. Root cause

### 2a. The structured fields are destroyed at the SDK boundary

`runner/claude_cli.py::_run_agent_sdk_async` consumes the `ResultMessage` at lines
174–186. It reads exactly five fields — `total_cost_usd`, `usage`, `num_turns`,
`result`, `is_error` — and reads **neither `subtype` nor `stop_reason`**:

```python
# runner/claude_cli.py:174-186
elif isinstance(message, ResultMessage):
    cost = message.total_cost_usd or 0.0
    usage = message.usage or {}
    itok = usage.get("input_tokens", 0)
    otok = usage.get("output_tokens", 0)
    num_turns = message.num_turns or 0
    if message.result:
        collected_text = [message.result]
    if message.is_error:
        returncode = 1
```

It then returns a dict whose `raw` is **rebuilt from scratch** rather than passed
through:

```python
# runner/claude_cli.py:196-203
"raw": {"result": text, "total_cost_usd": cost,
        "usage": {"input_tokens": itok, "output_tokens": otok},
        "agent_sdk": True, "turns": num_turns},
```

`subtype` and `stop_reason` are not in `raw`, not in the top-level dict, and not
in any field derived from either. **They cease to exist at line 196.** Every caller
downstream of `claude_cli.run()` sees a run that produced empty text and
`returncode=1`, indistinguishable from a dozen other failure modes.

### 2b. The classifier that would have caught it is never called

`result_classifier.classify()` requires precisely the two fields destroyed in 2a.
Grepping the whole repository for its name yields only:

- `runner/result_classifier.py` — the definition
- `tests/test_result_classifier.py` — its own unit test
- `tests/test_all_modules_importable.py` — a generic import smoke check

**No production module imports it.** It is dead code: correct, tested, and wired to
nothing. Even if it were called, 2a guarantees it could never return `True` on the
SDK path, because the keys it inspects never arrive.

### 2c. The compensating mechanism is a regex over prose

Because the structured signal is gone, `runner/auto_remediate.py` recovers the same
condition by pattern-matching free text:

```python
# runner/auto_remediate.py:48
_MAX_TURNS = re.compile(r"max_turns|maximum number of turns|reached.*turn.*limit", re.I)
```

It sits in a block of fourteen sibling regexes (lines 38–52) that classify failures
by scraping note/log strings. This is the downstream symptom, and it is fragile in
three specific ways:

1. It fires only if some upstream component happened to write the words
   `max_turns` into a note. Nothing guarantees that — see 2a.
2. `_PARKED` (line 47) also matches the literal `tool use`. A `tool_use` failure
   whose note contains that phrase can be classified **parked** rather than
   **max-turns**, routing it to "near-zero expected value, keep queued" instead of
   the retry-with-cap path at lines 132–137. One of the ten
   `economic-scheduler-revenue` tasks does carry `[ev-low-priority: near-zero
   expected value…]`.
3. Regex order decides the verdict, so adding any new pattern can silently
   re-route an existing failure class.

### 2d. Why this specific task looped

`stop_reason: "tool_use"` means *cut off mid-tool-call*, which by construction
yields no committable diff. The runner sees an empty result, and `_NOOP` (line 41,
`no committable|changed nothing|no file changes|agent run failed`) is the pattern
most likely to match. `_NOOP` routes to re-plan/sharpen — it re-runs the task with a
rewritten prompt rather than raising the turn budget, which is the one intervention
that would address a turn-budget exhaustion. The task history is consistent with
that loop: attempt counts of **10** on
`backlog-batch-beethoven-d00ef24-economic-scheduler-revenue-create-revenue-module`,
and `preflight: exhausted 5 attempts without success` on
`dropbox-economic-scheduler-revenue-revenue-focused-slice-2` before quarantine.

*Caveat:* the attempt counts are real, the causal link to `_NOOP` specifically is
inference from the routing table, not from an observed log line for this session.

---

## 3. Summary

| # | Finding | Evidence |
|---|---|---|
| 1 | The named session log does not exist in any queryable store | `session_actions` count = 0; no other `session_id` column in the schema |
| 2 | **Root cause:** `subtype` / `stop_reason` are dropped when the SDK result is repacked | `runner/claude_cli.py:174-186`, `:196-203` |
| 3 | The classifier for this exact condition has no production caller | `runner/result_classifier.py:18`; repo-wide grep finds only its own test |
| 4 | Failure class is instead recovered by regex over prose | `runner/auto_remediate.py:48`, siblings at `:38-52` |
| 5 | `_PARKED` (`:47`) can shadow `_MAX_TURNS` (`:48`) for the same failure | both match `tool use` / `tool_use` text |
| 6 | Turn exhaustion is likely routed as a no-op and re-planned rather than re-budgeted | `auto_remediate.py:41` vs `:132-137`; attempt=10 / "exhausted 5 attempts" in the task rows |

Findings 2 and 3 are the root cause. Findings 4–6 are consequences, and finding 1 is
the direct result of 2 — a failure whose structured identity is discarded cannot be
logged in a form anyone can later query, which is why this analysis had to be done
from source rather than from the session it names.

## 4. Deliberately not done

No fix is proposed or applied, per the task instruction. For whoever picks up the
remediation: the smallest change consistent with these findings is to preserve
`subtype` and `stop_reason` through `claude_cli.py`'s return dict and call the
existing `result_classifier.classify()` on it, rather than to add a fifteenth regex.
