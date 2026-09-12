#!/usr/bin/env python3
"""
prompt_bandit_retrain.py — re-explore the prompt bandit after a low-EV shelving.

WHY THIS FILE AND NOT THE ONE THE TASK NAMED. The original spec targets
`beethoven/bandit.py`, `prompts/bandit_evolved.txt` and `python -m beethoven.bandit
evolve`. None of those exist in this repository and the task has already been blocked once
for that reason. The intent, though, is concrete and implementable against what IS here:
the prompt bandit is `runner/prompt_evolution_bandit.py` (arms = prompt-variant ids,
epsilon-greedy, acceptance gate), the template evolver is `runner/prompt_evolution.py`,
and this module is the retrain entrypoint that was missing. So the spec is re-scoped to
real paths rather than blocked a second time.

WHAT A RETRAIN IS. A bandit that has been running long enough for `epsilon` to decay is
committed to its incumbent arm; that is correct in steady state and wrong after the
queue-velocity PID shelved work for low EV, because the reward signal that produced the
incumbent is exactly the one under suspicion. Retraining re-enters exploration: a raised
epsilon, decay disabled for the run, and an acceptance budget long enough that a variant
cannot be promoted on a handful of lucky pulls.

Defaults follow the original spec's numbers:
    epsilon = 0.30   (vs the 0.15 steady-state default)
    budget  = 50     trials before accept() may promote anything

Usage:
    python3 runner/prompt_bandit_retrain.py evolve --max-iter 10
    python3 runner/prompt_bandit_retrain.py evolve --max-iter 10 --out prompts/bandit_evolved.txt
    python3 runner/prompt_bandit_retrain.py validate-prompt prompts/bandit_evolved.txt

Fail-soft throughout: a retrain that cannot run returns a result saying so. It never
raises into the caller and never writes a prompt file it could not validate.
"""
import argparse
import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prompt_evolution  # noqa: E402
import prompt_evolution_bandit as peb  # noqa: E402

#: Spec defaults. Env-overridable so a retrain is a config change, not a patch.
RETRAIN_EPSILON = float(os.environ.get("ORCH_PROMPT_RETRAIN_EPSILON", "0.30") or 0.30)
RETRAIN_BUDGET = int(os.environ.get("ORCH_PROMPT_RETRAIN_BUDGET", "50") or 50)
#: Decay is disabled during a retrain: decaying epsilon mid-re-exploration would
#: reproduce the premature commitment the retrain exists to undo.
RETRAIN_DECAY = 0.0

DEFAULT_OUT = os.path.join("prompts", "bandit_evolved.txt")

#: The baseline arm. Always present so a retrain has an incumbent to beat and can never
#: promote a variant merely because it was the only one measured.
BASELINE_ARM = "baseline"

#: Structural variants the evolver can express today. Kept small on purpose: an arm that
#: is never pulled enough to clear the budget is noise, not exploration.
DEFAULT_ARMS = (BASELINE_ARM, "with_examples", "with_acceptance", "with_constraints")

#: A prompt must survive this to be written out. "Parseable" for a prompt template means
#: it is non-empty text with at least one instruction line — not that it is valid JSON.
MIN_PROMPT_CHARS = 20


def validate_prompt(text):
    """Return (ok, reason). A prompt is valid when it is non-empty and parseable.

    Deliberately strict about the empty-ish cases and permissive about content: the
    failure this guards is an evolve run writing a blank or whitespace-only file and a
    later cycle loading it as the live template.
    """
    if text is None:
        return False, "prompt is None"
    if not isinstance(text, str):
        return False, f"prompt is {type(text).__name__}, expected str"
    stripped = text.strip()
    if not stripped:
        return False, "prompt is empty or whitespace only"
    if len(stripped) < MIN_PROMPT_CHARS:
        return False, f"prompt is {len(stripped)} chars, minimum is {MIN_PROMPT_CHARS}"
    if not any(line.strip() for line in stripped.splitlines()):
        return False, "prompt has no non-blank lines"
    return True, ""


def _reward_for(arm_id, rng):
    """Reward signal for one trial.

    `prompt_evolution_bandit.load_performance()` is the real source and is a documented
    stub until `outcomes.prompt_variant` exists, so a retrain run today has no historical
    rewards to fold in. Rather than inventing a fake preference, every arm draws from the
    same distribution: the run then measures the bandit's own mechanics (does exploration
    reach every arm, does the budget hold promotion back) without asserting a winner the
    data cannot support. When the column lands, this is the single function to replace.
    """
    return float(rng.random())


def retrain(max_iter=10, arms=None, epsilon=None, budget=None, rng=None, warm=True):
    """Re-explore the prompt bandit. Returns a result dict; never raises.

    Result keys:
        ok, iterations, arms, epsilon, budget, best_arm, accepted, stats, warm_started
    """
    result = {
        "ok": False, "iterations": 0, "arms": [], "epsilon": None, "budget": None,
        "best_arm": "", "accepted": [], "stats": {}, "warm_started": 0, "error": "",
    }
    try:
        arm_ids = list(arms or DEFAULT_ARMS)
        if BASELINE_ARM not in arm_ids:
            arm_ids.insert(0, BASELINE_ARM)
        eps = RETRAIN_EPSILON if epsilon is None else float(epsilon)
        pulls = RETRAIN_BUDGET if budget is None else int(budget)
        rng = rng or random.Random(0)

        # Reinitialise: a fresh Bandit rather than the module singleton, so a retrain
        # cannot corrupt the live selector if it is abandoned half way through.
        bandit = peb.Bandit(arm_ids=arm_ids, epsilon=eps, decay=RETRAIN_DECAY,
                            min_pulls=pulls)

        if warm:
            try:
                for arm_id, rewards in (peb.load_performance() or {}).items():
                    if arm_id not in arm_ids:
                        continue
                    for reward in rewards:
                        bandit.update(arm_id, reward)
                        result["warm_started"] += 1
            except Exception:
                pass  # warm start is an optimisation; a cold retrain is still valid

        accepted = []
        for _ in range(max(0, int(max_iter))):
            arm = bandit.select_action(arm_ids, rng=rng)
            if not arm:
                break
            bandit.update(arm, _reward_for(arm, rng))
            result["iterations"] += 1
            if bandit.accept(arm) and arm not in accepted:
                accepted.append(arm)

        stats = bandit.stats() or {}
        result.update({
            "ok": True, "arms": arm_ids, "epsilon": eps, "budget": pulls,
            "best_arm": stats.get("best_arm") or "", "accepted": accepted, "stats": stats,
        })
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result


def _write_atomically(path, text):
    """Replace `path` with `text` in one step, or leave it exactly as it was.

    evolve() promises that "a retrain that produces nothing usable must leave the
    previous prompt in place rather than truncate it", and validate_prompt() enforces
    that for content the retrain can see. It could not enforce it for the write:
    `open(path, "w")` TRUNCATES on open, so a crash, a full disk or a SIGKILL between
    the truncate and the write left a zero-byte live prompt template behind — the very
    blank prompt the guard exists to prevent, arrived at by the one route the guard
    could not inspect. Every later task would then load an empty template.

    Written to a sibling temp file, flushed and fsynced, then os.replace()d into
    position. os.replace is atomic on POSIX for a same-filesystem rename, so a reader
    sees either the old prompt or the new one and never a partial file. The temp file
    is a sibling rather than /tmp precisely so the rename cannot cross a filesystem.
    """
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory or None,
                               prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Includes KeyboardInterrupt/SystemExit: an abandoned run must not leave the
        # temp file behind, and must not have touched the live prompt at all.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def evolve(max_iter=10, out_path=None, base_template=None, arms=None,
           epsilon=None, budget=None, rng=None):
    """Retrain, evolve the template with the learned signal, and persist it.

    Returns {"ok", "path", "prompt", "retrain", "reason"}. The file is written ONLY when
    the evolved prompt validates — a retrain that produces nothing usable must leave the
    previous prompt in place rather than truncate it.
    """
    outcome = {"ok": False, "path": "", "prompt": "", "retrain": {}, "reason": ""}
    try:
        report = retrain(max_iter=max_iter, arms=arms, epsilon=epsilon,
                         budget=budget, rng=rng)
        outcome["retrain"] = report

        template = base_template if base_template is not None else _default_template(report)
        try:
            evolved = prompt_evolution.evolve_template(template)
        except Exception:
            evolved = template  # fail-soft: an unevolved template still beats no template
        evolved = evolved or template

        ok, reason = validate_prompt(evolved)
        if not ok:
            outcome["reason"] = f"evolved prompt rejected: {reason}"
            return outcome

        path = out_path or DEFAULT_OUT
        _write_atomically(path, evolved if evolved.endswith("\n") else evolved + "\n")

        outcome.update({"ok": True, "path": path, "prompt": evolved})
        return outcome
    except Exception as exc:
        outcome["reason"] = str(exc)
        return outcome


def _default_template(report):
    """The seed template a retrain evolves from when the caller supplies none.

    Records the retrain parameters in the template itself so a prompt file on disk can be
    traced back to the run that produced it — an evolved prompt with no provenance is not
    auditable, and this repo's proof rules are explicit that a claim needs a receipt.
    """
    report = report or {}
    return (
        "# Evolved task prompt\n"
        "\n"
        f"<!-- retrain: epsilon={report.get('epsilon')} budget={report.get('budget')} "
        f"iterations={report.get('iterations')} best_arm={report.get('best_arm') or 'none'} -->\n"
        "\n"
        "Implement the smallest change that satisfies the acceptance criteria.\n"
        "Locate the existing owner module before adding new files.\n"
        "Reuse the project's helpers and naming conventions.\n"
        "Add or update the narrowest test that proves the requested behaviour.\n"
        "Run the project's build and test commands before finishing.\n"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="prompt_bandit_retrain",
                                     description="Retrain and evolve the prompt bandit.")
    sub = parser.add_subparsers(dest="command", required=True)

    evolve_cmd = sub.add_parser("evolve", help="retrain and write the evolved prompt")
    evolve_cmd.add_argument("--max-iter", type=int, default=10)
    evolve_cmd.add_argument("--out", default=DEFAULT_OUT)
    evolve_cmd.add_argument("--epsilon", type=float, default=None)
    evolve_cmd.add_argument("--budget", type=int, default=None)

    validate_cmd = sub.add_parser("validate-prompt", help="validate a prompt file")
    validate_cmd.add_argument("path", nargs="?", default=DEFAULT_OUT)

    args = parser.parse_args(argv)

    if args.command == "evolve":
        outcome = evolve(max_iter=args.max_iter, out_path=args.out,
                         epsilon=args.epsilon, budget=args.budget)
        print(json.dumps({k: v for k, v in outcome.items() if k != "prompt"},
                         indent=2, default=str))
        return 0 if outcome["ok"] else 1

    try:
        with open(args.path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        print(f"validate-prompt: cannot read {args.path}: {exc}")
        return 1
    ok, reason = validate_prompt(text)
    print(f"validate-prompt: {args.path}: {'OK' if ok else 'INVALID — ' + reason}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
