# Ollama host resource incident — 2026-09-12

## Observed cause

On the 48 GiB development Mac, Ollama 0.34.0 loaded `qwen3.5:27b-mlx`
with a 16,384-token context. Its API reported approximately 20.54 GiB of
resident allocation. The server had reported approximately 10.1 GiB of free
system memory, despite a larger GPU availability estimate. Wired/compressed
memory and active swapping then competed with local builds. Process RSS alone
understated the Metal allocation; high CPU usage alone was not the diagnosis.

The active Consilium scheduler supplied the large-model/context defaults. The
old shared guard admitted small models without locking, proceeded unslotted
after a lock timeout, and proceeded after memory admission timed out or lacked
telemetry. Unloading after every request also caused repeated cold loads.

## Protection contract

- All cooperating local inference shares one lock, including small models.
- Unknown telemetry, resource pressure, lock contention and over-budget models
  defer work. A timeout is never permission to bypass admission.
- The default per-model allocation budget is 8 GiB, with at least 8 GiB of
  host headroom. Check actual resident allocation and additional context demand.
- Requests have bounded context, output, deadline and finite residency. Reject
  oversized input rather than silently truncating task evidence.
- Admission does not unload another client's model or silently change to a
  smaller model or paid provider. Model choice remains a routing decision.
- A deferred job is not a completed job. Record a reason-only capacity receipt,
  preserve its last completion, and let other eligible work progress.
- A local coding driver without a verified bounded-context contract must defer;
  this must not send the task into generic repair/provider fallback.

## Local native configuration

The existing `ai.ollama.env` LaunchAgent now sets:

```text
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_QUEUE=2
OLLAMA_KEEP_ALIVE=30s
OLLAMA_CONTEXT_LENGTH=4096
```

The native app restarted at approximately 20:25 UTC; the new server log confirms
all five values. The prior effective startup configuration is preserved at
`/private/tmp/ai.ollama.env.before-20260912.plist`. Models were not deleted.
Memory pressure returned to normal and the existing Apparently preview recovered.

These settings constrain the native scheduler; they are not a whole-host RAM
limit. Per-request values can override native defaults, so caller admission is
also necessary. Login startup ordering should be checked after a future login.
Direct clients outside the guarded paths can still request large models.

Sources: [Ollama FAQ](https://docs.ollama.com/faq),
[0.34.0 MLX memory admission](https://github.com/ollama/ollama/blob/v0.34.0/x/mlxrunner/client.go).

## Verification and rollout

The focused resource/caller suites pass: **203 tests and 67 subtests**. The
Consilium scheduler's 28 hermetic tests also pass in the active checkout after
rollout. All 21 scoped destination files were byte-verified against the tested
source, preserving the active worktree's unrelated changes. The existing
`com.claudeorchestrator.consilium` service was bootstrapped from its original
plist after that verification; its regular 600-second schedule is restored.
No duplicate scheduler or extra manual business job was launched.

A real local `nomic-embed-text:latest` request returned 768 finite dimensions
in 0.305 seconds, with a 512-token context and 15-second idle residency. Host
pressure remained normal; available memory stayed above the 8 GiB reserve.
The model then unloaded naturally (`/api/ps` empty), and the existing Apparently
preview returned HTTP 200 in 69 ms. This is a small embedding utility check,
not a legal-model capability test. The 27B model was denied read-only by its
allocation budget; the 3B completion model was deferred for insufficient
additional headroom, without lowering the guard to force a smoke test.

The broader Consilium branch has two pre-existing `test_ci_offline` failures
about sentinel stash preservation. Those files are unchanged by this patch.
The fresh canonical staging base passes all 80 offline guard tests. Shared
code is being integrated separately so unrelated Consilium feature work is
not promoted as part of this hotfix.

The canonical checkout and the active Consilium worktree contain unrelated
work. Preserve it; promote shared code through `orchestrator/dev` using an
isolated branch, not a direct production push or a whole feature-branch merge.

## Operational limits and recovery

Inspect `host_admission_status()` and `admission_status(model)` before inference;
both are read-only. A healthy small-model smoke test is useful evidence, not
validation of a large legal model or a real legal workflow. Do not stress-test
by reloading the 27B model during recovery.

If an automated caller repeatedly defers, inspect its reason and routing
requirements. Do not disable the guard, increase budgets blindly, substitute
weaker legal reasoning, or buy cloud capacity as a resource workaround. Preserve
the original model/task intent and fix or explicitly choose its execution route.
