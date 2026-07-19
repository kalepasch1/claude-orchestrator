from pathlib import Path


def test_nuxt_generated_types_are_not_shared_between_worktrees():
    script = (Path(__file__).parents[1] / "setup-worktrees.sh").read_text()
    warm_loop = script.split("for depdir in", 1)[1].split("; do", 1)[0]
    assert ".nuxt" not in warm_loop
    assert "nuxi prepare" in script
