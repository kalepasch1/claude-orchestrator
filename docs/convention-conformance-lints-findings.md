# Convention-conformance lints — what the linter would require to be enforceable

Analysis of `tools/convention_lint.py` against the live `runner/` tree, plus the minimum
change that makes its output actionable.

## Measurement

`python3 tools/convention_lint.py --json` on the default check paths, before this change:

| rule | findings | true positives |
| --- | ---: | ---: |
| `FAIL_SOFT_ERROR` | 65 | not assessed here |
| `HARDCODED_SECRET` | 9 | **0** |
| **total** | **74** | |

Every one of the nine `HARDCODED_SECRET` findings was false. That matters more than the
count: the linter is wired into `.pre-commit-hooks.yaml` and exits non-zero, so a rule
whose entire output is false is not a strict gate. It is a gate that teaches people to
pass `--no-verify`, at which point every other rule stops being enforced too. The
repository already learned this once — the `TEST_EXEMPT_RULES` block added earlier
carries the same reasoning about a 72% noise rate.

## The nine findings, verbatim

| site | source line | why it is not a secret |
| --- | --- | --- |
| `runner/agent_market.py:413` | `author_model = ""` | `"AUTH"` matched inside `author`; value empty |
| `runner/deploy_watch.py:50,52` | `auth_hint = ""` | empty string |
| `runner/fleet_control.py:133` | `IGNORE_CREDENTIAL = "credential-marker"` | sentinel marker constant |
| `runner/ploeh_s2s_pricing.py:243` | `os.environ["PLOEH_S2S_SECRET"] = "test-key"` | placeholder value in a test path |
| `runner/verifier_marketplace.py:11,13,15` | `author_provider = ""` | `"AUTH"` matched inside `author`; value empty |
| `runner/provider_failover_sla.py:121` | `credential_fp = ""` | a fingerprint is deliberately *not* the credential; value empty |

Five of the nine are the empty string. An empty literal cannot leak anything, so the rule
was reporting a class of finding that is unfalsifiable by construction.

## Root cause

Two independent defects in `_check_hardcoded_secrets`, both in the original rule:

1. **Unanchored substring matching on the identifier.**
   `re.compile('|'.join([... 'AUTH', 'CREDENTIAL' ...]), re.IGNORECASE).search(var_name)`
   matches `AUTH` inside `author_model` and `author_provider`, and `CREDENTIAL` inside
   `IGNORE_CREDENTIAL`. Six of nine findings come from this alone.

2. **The assigned value was never examined.**
   The rule fired on the *name* and only skipped values starting with `$`. So
   `auth_hint = ""` and `PLOEH_S2S_SECRET = "test-key"` were reported as hardcoded
   secrets. Whether something is a hardcoded secret is a property of the value; the name
   only tells you where to look.

## Change applied

- `_identifier_words()` splits identifiers on snake_case and camelCase boundaries, so
  keywords match whole words. `author_model` → `{author, model}` no longer matches
  `auth`; `auth_token` → `{auth, token}` still does.
- `_looks_like_secret_value()` is a new value-side gate, and it runs *first*: a name that
  merely mentions credentials costs nothing until a secret-shaped literal is assigned. It
  rejects empty/short strings, `$`-placeholders, values containing whitespace (prose, not
  credentials), known placeholder vocabulary (`test`, `marker`, `example`, `changeme`, …),
  and values with fewer than five distinct characters.
- Bare `key` was removed from the keyword set. This repo names `fleet_config` rows
  `STATE_KEY`, `BUDGET_KEY`, `PRESSURE_KEY`, `CONTROL_KEY` — those hold the *name of a
  config row*. Including bare `key` traded the original 9 false positives for 21.
  `key` now only counts next to a qualifier: `api_key`, `private_key`, `access_key`,
  `signing_key`, `encryption_key`.

## Result

| rule | before | after |
| --- | ---: | ---: |
| `HARDCODED_SECRET` | 9 (9 false) | **0** |
| `FAIL_SOFT_ERROR` | 65 | 65 (untouched) |

Test suite: `tests/test_convention_lint.py` + `runner/tests/test_convention_lint_test_exemption.py`
— 34 passing before, **41 passing** after. The seven added cases pin each false-positive
shape found above, and `test_real_credentials_are_still_caught` asserts the tightening was
not bought with false negatives (GitHub PAT, long password, JWT-shaped Supabase key all
still flagged).

## What remains

`FAIL_SOFT_ERROR` at 65 findings has not been assessed for precision and is the obvious
next slice. Its current heuristic — "a public module-level function containing `raise`
with no `except` that returns" — will flag argument validation and re-raise-after-cleanup,
both of which are correct code. The same two-part discipline applies: check the property
you actually care about, and measure precision against the live tree before wiring the
result to a non-zero exit.
