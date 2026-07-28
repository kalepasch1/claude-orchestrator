import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import workflow_router as wr


def test_material_goes_governed_and_gated():
    p = wr.profile_for("Add ECP swap standby pricing with a Reg-adjacent compliance gate and a migration.")
    assert p.mode == "governed_heavy"
    assert p.material is True and p.qa is True and p.shard == "light"


def test_coherent_small_is_fast():
    p = wr.profile_for("# Build settings page\n\n## Layout\n...\n## Toggle\n...")
    assert p.mode == "fast_coherent"
    assert p.shard == "light" and p.qa is False and p.model_hint == "opus"


def test_trivial_is_cheap():
    p = wr.profile_for("rename the util and fix a typo")
    assert p.mode == "cheap_bulk" and p.model_hint == "haiku" and p.shard == "none"


def test_large_broad_nonmaterial_stays_parallel():
    txt = "".join(f"## Section {i}\n" + ("detail " * 200) + "\n" for i in range(8))
    p = wr.profile_for(txt)
    assert p.mode == "parallel_fleet" and p.shard == "full"


def test_explicit_override_wins():
    assert wr.classify("WORKFLOW: fast_coherent\nAdd a compliance swap gate") == "fast_coherent"


def test_env_override(monkeypatch=None):
    os.environ["PLAN_WORKFLOW"] = "cheap_bulk"
    try:
        assert wr.classify("some broad multi-section thing\n## a\n## b\n## c\n## d\n## e") == "cheap_bulk"
    finally:
        del os.environ["PLAN_WORKFLOW"]


def test_default_unchanged_for_unclassified():
    # a large, broad, non-material prompt reproduces historical wide-shard behavior
    txt = "".join(f"## Part {i}\n" + ("word " * 300) + "\n" for i in range(10))
    assert wr.profile_for(txt).mode == "parallel_fleet"
