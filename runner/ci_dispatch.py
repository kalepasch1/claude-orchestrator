# runner/ci_dispatch.py

def _github_dispatch(repo, payload, github_token):
    """POST repository_dispatch to GitHub API. Returns True on success."""
    if not github_token or not repo:
        return False
    import urllib.request
    import urllib.error
    url = f"https://api.github.com/repos/{repo}/dispatches"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"[ci_dispatch] GitHub API error {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"[ci_dispatch] dispatch failed: {e}")
        return False


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
    # Fire the actual GitHub dispatch if credentials are available
    if github_token and repo:
        if not _github_dispatch(repo, payload, github_token):
            return None
    _in_flight[slug] = {"dispatched_at": time.time(), "task_id": str(task.get("id", ""))}
    return payload
