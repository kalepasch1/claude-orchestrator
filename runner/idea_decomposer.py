#!/usr/bin/env python3
"""
Decompose a one-line idea into a task DAG using a cheap model.
Minimal viable: idea string → task graph with dependencies.
"""
import json
import sys
from typing import Optional

from anthropic import Anthropic


def decompose_idea(idea: str, model: str = "claude-3-5-haiku-20241022") -> dict:
    """
    Take a one-line idea and produce a minimal task DAG.
    Returns {"tasks": [{"id": str, "title": str, "description": str, "depends_on": [str]}]}
    """
    client = Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""You are a product decomposition expert. Given this one-line idea,
produce a JSON task graph with the MINIMUM viable set of tasks to ship an MVP.

Output ONLY valid JSON (no markdown, no explanation):
{{
  "tasks": [
    {{"id": "task-1", "title": "...", "description": "...", "depends_on": []}},
    {{"id": "task-2", "title": "...", "description": "...", "depends_on": ["task-1"]}}
  ]
}}

Use sequential IDs like task-1, task-2, etc.
Minimize the DAG. Each task must have a clear single responsibility.

Idea: {idea}"""
        }]
    )

    content = response.content[0].text
    # Extract JSON from potential markdown wrapping
    start = content.find('{')
    end = content.rfind('}') + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON found in response: {content}")

    json_str = content[start:end]
    return json.loads(json_str)


def validate_task_graph(graph: dict) -> None:
    """Validate that a task graph is well-formed."""
    if "tasks" not in graph:
        raise ValueError("Graph missing 'tasks' key")

    tasks = graph["tasks"]
    if not isinstance(tasks, list):
        raise ValueError("'tasks' must be a list")

    if not tasks:
        raise ValueError("'tasks' list cannot be empty")

    task_ids = set()
    for task in tasks:
        # Validate structure
        if not all(k in task for k in ["id", "title", "description", "depends_on"]):
            raise ValueError(f"Task missing required fields: {task}")

        task_ids.add(task["id"])

    # Validate all dependencies exist
    for task in tasks:
        for dep in task["depends_on"]:
            if dep not in task_ids:
                raise ValueError(f"Task {task['id']} depends on non-existent task {dep}")

    # Check for cycles (simple DFS)
    def has_cycle(task_id: str, visited: set, rec_stack: set) -> bool:
        visited.add(task_id)
        rec_stack.add(task_id)

        task = next(t for t in tasks if t["id"] == task_id)
        for dep in task["depends_on"]:
            if dep not in visited:
                if has_cycle(dep, visited, rec_stack):
                    return True
            elif dep in rec_stack:
                return True

        rec_stack.remove(task_id)
        return False

    visited = set()
    for task in tasks:
        if task["id"] not in visited:
            if has_cycle(task["id"], visited, set()):
                raise ValueError("Task graph contains a cycle")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: idea_decomposer.py 'one-line idea'")
        sys.exit(1)

    idea = sys.argv[1]
    result = decompose_idea(idea)
    validate_task_graph(result)
    print(json.dumps(result, indent=2))
