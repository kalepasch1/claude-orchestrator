import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import self_deploy_watchdog as wd

FAIL_LOG = '''
runner/economic_scheduler.py line 27
    <<<<<<< HEAD
E   SyntaxError: invalid syntax
self_deploy: BLOCKED -- tests failing
{
  "deployed": false,
  "reason": "canary_failed",
  "running_commit": "b81d6d94881a9bb9b7c8385aca7de3e577f796de",
  "head_commit": "8ce2905c37e1e00fa24d6d4c8b038c1ad95a2ad5"
}
'''

OK_LOG = '''
{
  "deployed": false,
  "reason": "up-to-date",
  "running_commit": "aaaa",
  "head_commit": "aaaa"
}
'''

def test_parses_last_verdict():
    v = wd.parse_last_verdict(FAIL_LOG)
    assert v["reason"] == "canary_failed"
    assert v["head"].startswith("8ce2905c")

def test_canary_fail_triages_and_files():
    filed = []
    r = wd.watch(FAIL_LOG, enqueue_fn=lambda rec: filed.append(rec))
    assert r["action"] == "triaged"
    assert r["class"] == "conflict-marker"
    assert r["filed"] is True
    assert filed[0]["kind"] == "remediation" and filed[0]["priority"] == 1

def test_up_to_date_no_action():
    r = wd.watch(OK_LOG, enqueue_fn=lambda rec: None)
    assert r["action"] == "none"

def test_empty_log():
    assert wd.watch("", enqueue_fn=lambda rec: None) == {"action": "none"}
