---
id: WORDSTAT-002
title: 'Journal read: an unreadable row is a cache miss with one warning (T432)'
status: queue
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: architect
worker: claude-code
type: bugfix
owns_paths:
- src/rb_wordstat/core/cache.py
- tests/test_cache.py
test_paths:
- tests/test_cache.py
docs: none
tools: []
worker_args: null
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- uv run pytest tests/test_cache.py -q
- python3 scripts/check_command_docstrings.py
resident: null
tool: null
pr: null
---

The dev journal (PostgreSQL cache.wordstat_responses) holds rows that are not zlib (a bytea->text copy). ResponseCache.latest (src/rb_wordstat/core/cache.py) raises zlib.error 'Error -3 ... incorrect header check' or a JSON error. Decision (marketer, T432): catch zlib.error and ValueError (JSON/Unicode) around decompress+loads in latest, log one warning (logging.getLogger(__name__), same style as core/client.py) with row id and provider, return None. No older-row logic. The normal request then appends a good row, which latest returns next time (order by fetched_at desc). Add the id column to the select.

## Acceptance

- Given a journal row whose data is not zlib (for example hex text starting with backslash-x78, first byte 0x5c, or plain JSON), When ResponseCache.latest reads it, Then it returns None and logs exactly one warning with the row id and provider [check: tests/test_cache.py]
- Given WordstatClient with use_cache and that bad row, When it searches, Then it calls the provider once and writes a new good row, and the next cached search hits it [check: tests/test_cache.py]

## How to test

Unit test in tests/test_cache.py: insert a bad row with sa.insert(responses) on the _local_database SQLite, FakeProvider already used there; caplog for the warning. Commit the red test first.

## Out of scope

- No older-row fallback; no migration or cleanup command; no change to put, stats, entries; touch no database but the test SQLite.
