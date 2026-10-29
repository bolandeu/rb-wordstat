---
id: WORDSTAT-002
title: 'Journal read: an unreadable row is a cache miss with one warning (T432)'
status: in_review
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
- uv run pytest tests/test_cache.py -q --no-cov
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

## Feedback

### Blocked: check_broken (check uv run pytest tests/test_cache.py -q, exit 1, sign red with every test passed, tail src/rb_wordstat/providers/__init__.py                    14      4    71%   31-34
src/rb_wordstat/providers/base.py                       184     79    57%   98-102, 113-115, 120, 135, 160-162, 200-206, 214-224, 228-241, 266-268, 273-274, 278, 282-319, 346-347
src/rb_wordstat/providers/xmlriver.py                    45     24    47%   29, 33-40, 43, 47-58, 62-63
src/rb_wordstat/providers/xmlstock.py                    41     22    46%   30, 34-43, 46, 56-62, 66-69
-----------------------------------------------------------------------------------
TOTAL                                                  2245    921    59%

11 files skipped due to complete coverage.
FAIL Required test coverage of 90.0% not reached. Total coverage: 58.98%
9 passed in 1.57s)
