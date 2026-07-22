

def promote_if_smoke_passed(preview_url, smoke_result, prod_url=None):
    """Promote to prod only if smoke tests passed. Idempotent.

    Args:
        preview_url: URL of the preview deployment.
        smoke_result: dict with 'passed' bool from smoke_test_runner.
        prod_url: optional production URL for reference.

    Returns:
        {"success": bool, "reason": str, ...}
    """
    if not smoke_result or not smoke_result.get("passed"):
        return {"success": False, "reason": "smoke tests did not pass",
                "smoke_passed": False}
    result = promote_to_prod(preview_url, prod_url)
    result["smoke_passed"] = True
    result["reason"] = "promoted" if result.get("success") else result.get("error", "unknown")
    return result


def rollback_to_previous(prev_config):
    """Roll back to a previous production config. Idempotent/safe to retry.

    Args:
        prev_config: dict with 'deployment_id' of the previous prod deployment.

    Returns:
        {"success": bool, "error"?: str}
    """
    if not prev_config:
        return {"success": False, "error": "no prev_config provided"}
    dep_id = prev_config.get("deployment_id") or prev_config.get("uid") or prev_config.get("id")
    if not dep_id:
        return {"success": False, "error": "prev_config has no deployment_id"}
    return rollback_prod(dep_id)
