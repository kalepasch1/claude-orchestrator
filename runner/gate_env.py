"""One environment for every gate that shells out to a project's toolchain.

WHY THIS IS A MODULE AND NOT A merge_train HELPER
-------------------------------------------------
2026-09-01: every merge-train TESTFAIL on this host was `bash: npm: command not found`.
The gates shell out with `bash -lc`, which sources ~/.bash_profile -- but the operator's
shell is zsh and nvm is initialised in ~/.zshrc, so a login bash never sees node. Under
launchd there is no interactive shell at all and PATH is minimal. Finished, working code
was marked TESTFAIL for an environment fault, burned its redo cap, and was abandoned.

The fix went into merge_train._gate_env() and was applied at merge_train's own suite call
-- and nowhere else. Measured 2026-09-02, the day after: `[gate-env] node not on PATH`
had fired 15 times, and `bash: npm: command not found` had ALSO appeared 14 more times in
the same log, every one of them prefixed `overlay:<sha>`, which is release_train's return
shape, from a `bash -lc` that never received the repaired environment.

Reproduced directly, same host, same command, launchd's PATH:

    bash -lc 'npm --version'   [inherited PATH]   rc=127  bash: npm: command not found
    bash -lc 'npm --version'   [gate env]         rc=0    11.19.0

A fix that lives in one caller is not a fix for a fleet with five callers. Every gate that
runs a project's own command imports this.
"""
import os

_CACHE = None


def node_bin_dir():
    """Best guess at the directory holding npm/node on this host.

    ORCH_NODE_BIN wins if set. Otherwise the newest nvm install, then the usual
    package-manager prefixes. Returns "" when node cannot be located at all.
    """
    explicit = os.environ.get("ORCH_NODE_BIN", "").strip()
    if explicit and os.path.isfile(os.path.join(explicit, "npm")):
        return explicit
    import glob
    cands = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin")), reverse=True)
    cands += ["/opt/homebrew/bin", "/usr/local/bin"]
    for c in cands:
        if os.path.isfile(os.path.join(c, "npm")):
            return c
    return ""


def gate_env(base=None):
    """os.environ with node guaranteed on PATH. Pass this as `env=` to every gate.

    `base` lets a caller extend an environment it has already built (an overlay's
    NODE_ENV, a test's isolated env) instead of replacing it. Only the default,
    base-is-None case is cached, because that is the one every gate shares.
    """
    global _CACHE
    if base is None and _CACHE is not None:
        return _CACHE
    env = dict(os.environ if base is None else base)
    nb = node_bin_dir()
    if nb and nb not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = nb + os.pathsep + env.get("PATH", "")
        if base is None:
            print(f"[gate-env] node not on PATH; prepending {nb}", flush=True)
    if base is None:
        _CACHE = env
    return env


def reset_cache():
    """Drop the memoised environment. For tests, and for a PATH change mid-process."""
    global _CACHE
    _CACHE = None
