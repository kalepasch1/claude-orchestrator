#!/usr/bin/env python3
"""Model selection strategy for orchestration tasks."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def select_preflight_model(task_id=None):
    """Select model for preflight triage phase."""
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
