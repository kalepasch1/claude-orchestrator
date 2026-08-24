# test-plan.md — hermetic network guard (`runner/tests/conftest.py::_hermetic`)

The specification `test_hermetic_guard_loopback.py` is written against. It existed
only as a prose docstring inside the test file, which meant every re-queue of the
`canary-claude-27-slice-3-update-tests-checks-*` family started by re-deriving it.
Written down here once, so the assertions can be checked against a spec instead of
against themselves.

## Contract

The suite must not depend on any host but this one. `_hermetic` is an autouse
fixture that enforces that by refusing outbound IP connections, unless the test
carries `@pytest.mark.allow_network`.

**Loopback is not the network.** The rationale for the guard is "the suite's
runtime and its pass/fail become someone else's uptime". Nobody else's uptime is
involved in `127.0.0.1`, so loopback is exempt — a test that starts a server in
its own process and scrapes it is testing itself, not the internet.

## Core scenario

A test binds an HTTP server on `127.0.0.1:0` inside the test process and reads it
back over `urllib`. This must succeed, both by IP and by the name `localhost`, and
it must reach the test's own port — not the discard-port proxy the guard exports
into `http_proxy`. The original defect was exactly that: `no_proxy` was emptied, so
`http://127.0.0.1:<port>/metrics` was routed to `('127.0.0.1', 9)` and refused by
the guard's own plumbing rather than by the guard's rule.

Covered by `LoopbackReachesItsOwnServerTest`.

## Edge cases

A widened guard is only safe if its edge is exact. Each of these is a separate
assertion:

| # | Edge case | Expected |
|---|---|---|
| 1 | A real remote host (`example.com`, `8.8.8.8`) | refused — the guard is not defanged |
| 2 | `localhost`, `::1`, `[::1]`, `::ffff:127.0.0.1`, all of `127.0.0.0/8` | loopback |
| 3 | A name that merely *contains* "localhost" (`localhost.evil.com`, `notlocalhost.example.com`, `127.0.0.1.evil.com`) | **not** loopback — substring matching would be a hole |
| 4 | Near-miss octets (`128.0.0.1`, `27.0.0.1`, `127.0.0.256`) | not loopback |
| 5 | Garbage / unresolvable addresses (`None`, `b"\xff\xfe"`, `()`, objects) | not loopback — fails **closed**, never raises |
| 6 | Name resolution | `_is_loopback` performs no DNS: a lookup would itself be the remote dependency the guard prevents |
| 7 | LAN and wildcard addresses (`192.168.1.10`, `10.0.0.1`, `0.0.0.0`) | not loopback |
| 8 | **`connect_ex` to a remote host** | refused with `ECONNREFUSED` (111) as a *return value*, not an exception |
| 9 | `connect_ex` to our own loopback port | connects, returns 0 |
| 10 | The refusal's shape | `OSError` with `errno == 111` and "hermetic guard" in the message, so errno-inspecting callers behave as they would offline |

### Note on edge case 8

`connect_ex` is the same egress as `connect`, spelled so it returns an errno
instead of raising. The guard wrapped only `connect`, so `connect_ex` walked
straight out to the real network and did so *silently* — a hole that raises
nothing is indistinguishable from a suite with no remote dependencies. It is
blocked by returning 111 rather than raising, because raising would break callers
in a way they would never break on a genuinely offline machine.

## Out of scope

Child processes. `monkeypatch` cannot see a socket `git` opens, so children are
pointed at a dead discard-port proxy instead (`http_proxy=http://127.0.0.1:9`)
with loopback exempted via `no_proxy`. That is containment, not enforcement, and
is deliberately not asserted here.
