#!/usr/bin/env python3
"""Model selection strategy for orchestration tasks."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def select_preflight_model(task_id=None):
    """Return the model used for the preflight triage phase.

    Preflight triage is the cheap first-pass rating of a queued task. It runs on every
    task, so the phase is deliberately pinned to a free local model: at fleet volume the
    triage pass would otherwise dominate spend while adding little over a local model's
    judgement. The returned value is a constant, not a routing decision.

    Args:
        task_id: Accepted for interface uniformity with the other ``select_*`` functions
            and with ``select_model_for_phase``, which calls every selector with the same
            signature. It is currently IGNORED — triage does not vary per task. Passing a
            task id will not change the result.

    Returns:
        str: The model identifier ``"local:deepseek-coder-v2:16b"``.

    Note:
        This value is pinned by contract tests (see
        ``runner/tests/test_relfix_pareto_2080_07171927.py::
        test_contract_preflight_triage_uses_local_deepseek``), so changing it is a
        contract change, not a tuning tweak.

        Recorded task prompts in this family describe this function as selecting
        ``google:gemini-2.0-flash`` for legal task classes, falling back to a default
        otherwise, and honouring a "qpd leader queue weight" parameter. It does NONE of
        those things: there is no task-class branching, no fallback, and no weight
        parameter. That description is documented here only so the next reader does not
        go looking for behaviour that was never implemented. Per-class routing lives
        elsewhere (``runner/model_router.py`` and ``runner/bandit.py``); the qpd figures
        that appear in pipeline-contract text are recorded telemetry about the chosen
        model, not an input to this function.
    """
    return "local:deepseek-coder-v2:16b"


def select_strategy_planner_model(task_id=None):
    """Select model for strategy planning phase."""
    return "deepseek:deepseek-v4-pro"


def select_agentic_coder_model(task_id=None):
    """Select model for agentic code generation."""
    return "claude-sonnet-4-6"


def select_qa_panel_models(task_id=None):
    """Select models for QA panel judges."""
    return ["deepseek:deepseek-v4-flash", "local:llama3.2:3b"]


def select_model_for_phase(phase, task_id=None):
    """Select model based on execution phase."""
    phase_map = {
        "preflight_triage": select_preflight_model,
        "strategy_planner": select_strategy_planner_model,
        "agentic_coder": select_agentic_coder_model,
        "qa_panel": select_qa_panel_models
    }
    fn = phase_map.get(phase)
    if fn:
        return fn(task_id)
    return None
