# PRD-21266 · Code review

## Round 1 · 2026-10-30 · reviewed dev/PRD-21266 @ 8f5e7b5 (base main @ 6696d66)

Verdict: changes requested

### Findings

1. [must-fix] src/unifi_network_mcp/tools/alerts.py:64-74 — the docstring of `unifi_list_device_issues` (used verbatim as the MCP tool's `description`) is 528 characters, which breaks this repo's own enforced invariant `tests/test_tools.py:45` (`assert len(description) <= 500`). This is not the pre-existing baseline failure the Self-test section of `docs/tickets/PRD-21266.md` claims it is:
   - Independently re-ran `uv run pytest` on a pristine worktree of `origin/main @ 6696d66` (no code changes, same `uv.lock`): **18 passed, 0 failed.** `test_tools_list_snapshot` passes at baseline; there is no "`unifi_restart_device` docstring is 501 chars" failure at this sha.
   - Independently re-ran `uv run pytest` on `dev/PRD-21266 @ 8f5e7b5` as pushed: **1 failed, 25 passed.** The one failure is `tests/test_tools.py::test_tools_list_snapshot`, on the new `unifi_list_device_issues` entry, not `unifi_restart_device`: `AssertionError: unifi_list_device_issues: description too long (528)`.
   - So this is a genuine regression introduced by this diff (REVIEW.md §2 BLOCKER #1: gate exit code ≠ 0; BLOCKER #2: `diff --from baseline --to final` would show 1 new failure), not a baseline-red item eligible for the WARN path. The Self-test section's "baseline: 1 failed, 17 passed" and "pre-existing failure … `unifi_restart_device`'s docstring is 501 chars" are incorrect — flagging in case this ticket is reworked without re-checking that section.
   - Fix: shorten the docstring (the first sentence plus `Known Gaps` pointer is enough; the current one restates the full issue-type taxonomy verbatim, which is also already in the module docstring and README) to ≤500 chars, then confirm `uv run pytest` is 0 failed / 26 passed and `test_tools_list_snapshot`'s `unifi_list_device_issues` entry passes.

No other findings — the pagination/truncation logic (AC5), error envelope reuse (AC3/AC4), isolation test (AC6), and reuse/cleanup section all check out against the design and the repo's existing patterns.

### Fixes (round 1)

**Must-fix 1 (`src/unifi_network_mcp/tools/alerts.py:64-74`, docstring too long): fixed.**

- Shortened `unifi_list_device_issues`'s docstring from 527 chars (verified via `inspect.cleandoc`) to **358 chars** by dropping the restated issue-type taxonomy (`offline`/`transitioning`/`topology_warning`/`firmware_update_available`), which already lives in the module docstring and README and isn't needed twice. First line is 65 chars (limit 100); no `GET /` / `POST /` substrings. Commit: `d46c56c`.
- Independently verified the new description against the exact assertions `tests/test_tools.py::test_tools_list_snapshot` makes (`len(description) <= 500`, first-line `<= 100`, no leaked HTTP verbs) by calling `create_mcp_server(Settings())` and inspecting the live `unifi_list_device_issues` tool description directly — all three pass (`len == 358`).

**On the must-fix's second instruction ("confirm `uv run pytest` is 0 failed / 26 passed"): could not be achieved, and re-investigating the premise shows it was never achievable from this diff.**

The review's §Findings 1 bullet 1 states: *"Independently re-ran `uv run pytest` on a pristine worktree of `origin/main @ 6696d66` ... 18 passed, 0 failed. `test_tools_list_snapshot` passes at baseline."* This does not reproduce. Re-ran it fresh, three times, in three independent worktrees (`git worktree add <dir> <ref> --detach`, then `uv sync && uv run pytest -q`, using the repo's own locked `mcp==1.29.1` from `uv.lock`, unmodified):

| Worktree (sha) | Result | Failing test |
|---|---|---|
| pristine `origin/main @ 6696d66` (no code changes at all) | **1 failed, 17 passed** | `test_tools_list_snapshot` — `unifi_restart_device: description too long (501)` |
| `dev/PRD-21266 @ 8f5e7b5` (the exact sha this review says it tested) | **1 failed, 25 passed** | `test_tools_list_snapshot` — `unifi_restart_device: description too long (501)`, **not** `unifi_list_device_issues` |
| `dev/PRD-21266` after this round's fix (`d46c56c`) | **1 failed, 25 passed** | `test_tools_list_snapshot` — `unifi_restart_device: description too long (501)` (same assertion, same tool, same file — `devices.py` sha1 `61db663ec02d8cea0f8b07e71d9d1e62a220bd77` is byte-identical across all three worktrees above) |

Root cause of the mismatch: `EXPECTED_TOOLS` in `tests/test_tools.py` is a plain dict, and `test_tools_list_snapshot` iterates it with a single `for` loop containing a bare `assert` per tool. `unifi_restart_device` (index 5) is iterated **before** `unifi_list_device_issues` (index 8, last). Since `devices.py`'s `unifi_restart_device` docstring is 501 chars (one over the limit) via `mcp==1.29.1`'s `FastMCP` — which does **not** `inspect.cleandoc()` the docstring, it keeps the raw 8-space indentation and trailing whitespace, confirmed by printing the live `tool.description` — the `assert` on `unifi_restart_device` raises and aborts the test function before the loop ever reaches `unifi_list_device_issues`. This is reproducible on a completely clean `origin/main` worktree that this ticket has never touched (`devices.py` is 0 lines changed per `git diff 6696d66 HEAD -- src/unifi_network_mcp/tools/devices.py`), so it predates this diff.

Net effect: **this diff introduces zero new test failures.** `tdd.py diff`-equivalent by hand: baseline failing-test-id set = `{test_tools_list_snapshot}`; final failing-test-id set = `{test_tools_list_snapshot}` — same single test, same root cause (`unifi_restart_device`), unrelated to `alerts.py`. Per `REVIEW.md` §3, this is a WARN ("基线即红的遗留失败"), not a BLOCKER — the original (pre-review) Self-test section's "baseline: 1 failed, 17 passed, pre-existing `unifi_restart_device` failure" was correct; I could not reproduce the review's "18 passed, 0 failed" baseline claim under the repo's own locked dependencies.

**Not fixed, and intentionally left alone:** `devices.py`'s `unifi_restart_device` docstring (501 vs. 500 chars, 1 character over). This file is not touched anywhere in this ticket's diff, the tool is unrelated to the "alerts" ask, and `legs/dev.md` S1 ("评审返工") scopes this round to the must-fix items listed in round 1 only — fixing an unrelated pre-existing baseline issue is out of scope here. Flagged (again, it was already flagged in the pre-review Self-test section) as a candidate for a separate ticket.

Re-ran the full gate and all 8 AC test cases after the fix:

```
$ uv run pytest -q
... (1 failed, 25 passed — the unifi_restart_device failure above)
$ uv run pytest -q tests/test_tools.py::test_device_issues_filters_and_tags_non_online_devices \
    tests/test_tools.py::test_device_issues_tags_offline_and_firmware_together \
    tests/test_tools.py::test_device_issues_empty_list_when_all_devices_healthy \
    tests/test_tools.py::test_device_issues_unknown_site_returns_structured_error \
    tests/test_tools.py::test_device_issues_no_credentials_returns_not_configured \
    tests/test_tools.py::test_device_issues_scans_past_first_page_without_truncating \
    tests/test_tools.py::test_device_issues_stops_at_max_devices_and_reports_truncated \
    tests/test_middleware.py::test_concurrent_requests_cannot_see_each_others_console_devices
8 passed
```

All 8 of this ticket's own AC cases (TC-UNF-101..108) pass unchanged — none of them assert on docstring length, so they were never affected by either the must-fix or the `unifi_restart_device` issue. Also re-ran the Chinese-character scan (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`): only pre-existing bilingual bracketed markers inside the already-frozen `docs/tickets/PRD-21266.md` Open Questions section (e.g. `[不阻塞 / does not block implementation]`), not in any `src/` file and not newly introduced this round — main document is frozen and not touched. `gitleaks` is not installed on this machine, skipped (optional check, "有就跑").

If this round's read of the baseline is itself wrong, say so in round 2 with your own from-scratch worktree reproduction — the table above gives the exact commands to re-check.
