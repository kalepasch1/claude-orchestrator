import hashlib,os,tempfile
from unittest.mock import patch

import ast_rewrite_ir,native_distiller,parallel_dispatch

def test_distiller_deduplicates_and_bounds_context():
    block="Change src/a.py safely.\n\n"
    out=native_distiller.distill({},block*1000)
    assert out["eligible"] and out["distilled_chars"] < 15000
    assert "unified diff" in out["prompt"]
    assert out["targets"] == ["src/a.py"]

def test_distiller_rejects_non_patch_capability():
    assert not native_distiller.distill({},"Use browser login then send email")["eligible"]

def test_typed_ast_rewrite_is_hash_guarded_and_validated():
    with tempfile.TemporaryDirectory() as repo:
        path=os.path.join(repo,"a.py"); before="def old():\n    return old()\n"
        with open(path,"w") as f:f.write(before)
        ir={"schema":ast_rewrite_ir.SCHEMA,"operations":[{"kind":"rename_symbol","path":"a.py",
            "old":"old","new":"new","before_hash":hashlib.sha256(before.encode()).hexdigest()}]}
        assert "def new" in ast_rewrite_ir.apply(repo,ir)["a.py"]
        ir["operations"][0]["before_hash"]="bad"
        try:ast_rewrite_ir.apply(repo,ir);assert False
        except ValueError:pass

def test_native_mode_holds_non_canary_until_direct():
    task={"slug":"ordinary","prompt":"change x","kind":"build"}
    with patch.dict(os.environ,{"ORCH_NATIVE_MODE":"canary"}):
        assert not parallel_dispatch._is_api_eligible(task)
    with patch.dict(os.environ,{"ORCH_NATIVE_MODE":"direct"}):
        assert parallel_dispatch._is_api_eligible(task)
