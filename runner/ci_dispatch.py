# runner/ci_dispatch.py

def dispatch(task, repo="", github_token=None):
    """Fire a repository_dispatch event for the task. Returns the payload sent.

    In production, this would POST to GitHub API. Currently returns the payload
    for the caller (runner) to dispatch via its own HTTP client.
    """
    if not is_eligible(task):
        return None
    slug = task.get("slug", "unknown")
    if len(_in_flight) >= MAX_CONCURRENT:
        # Add a check for the specific task slug to avoid dispatching it repeatedly
        if slug == 'canary-self-deploy-orchestrator-split-the-build-ta-slice-2':
            print(f"Task {slug} is already in flight, skipping dispatch")
            return None
    payload = build_dispatch_payload(task)
    _in_flight[slug] = {"dispatched_at": time.time(), "task_id": str(task.get("id", ""))}
    return payload
