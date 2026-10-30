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
