# Orchestration pipeline contract

The contract block stapled to the top of every task prompt records which model ran each
stage of the pipeline. This file documents the routing decisions behind those lines.

Owner module: [`runner/orchestration_pipeline_config.py`](../runner/orchestration_pipeline_config.py).

## Preflight Triage Model Selection Example

`preflight_triage_model(task_class)` returns the `provider:model` route for the preflight
triage stage — the cheap first-pass rating that decides whether a task is worth planning
in full.

It takes one argument and reads only its leading token, so both spellings work:

- the bare class, `"legal"`; and
- the decorated form the contract block emits, `"legal (need 9, risk legal_posture)"`.

Classes in `PREFLIGHT_ESCALATED_CLASSES` — `legal`, `security`, `compliance`, `privacy` —
escalate to `PREFLIGHT_ESCALATED_MODEL`. Everything else takes the configured default.
Escalation exists because a triage mistake on those classes is not symmetric: under-rating
a legal-posture change is far more expensive than the tokens saved by rating it cheaply.

### Worked example

```python
>>> from orchestration_pipeline_config import preflight_triage_model
>>> preflight_triage_model("legal (need 9, risk legal_posture)")
'google:gemini-2.5-flash'
>>> preflight_triage_model("build (need 6, risk standard)")
'local:llama3.2:3b'
```

A note on that value, because the request that produced this section asked for it to be
documented as `google:gemini-2.0-flash`: **it is not**. The escalated route is
`google:gemini-2.5-flash`, as `PREFLIGHT_ESCALATED_MODEL` defines and as
`preflight_triage_model("legal (need 9, risk legal_posture)")` actually returns. The
example above is generated from the function's real behaviour rather than transcribed,
and `runner/tests/test_orchestration_docs_contract.py` fails if this document and the
code ever disagree — a documented route that quietly stops matching the router is worse
than an undocumented one, because it is the version people quote in review.

### Configuration

| Setting | Env var | Default |
|---|---|---|
| Escalated route | `ORCH_PREFLIGHT_ESCALATED_MODEL` | `google:gemini-2.5-flash` |
| Default route | `ORCH_PREFLIGHT_MODEL` | `local:llama3.2:3b` |

Both are `ORCH_`-prefixed, so they are fleet-pushable through `fleet_control.py` rather
than edited per machine.

### Failure behaviour

Fail-soft, and deliberately toward the cheap route: `None`, an empty string, or an
unparseable class returns the default rather than raising. An unparseable task class is a
bug in the caller, and taking the escalated model on every such call would turn that bug
into an unbounded spend.
