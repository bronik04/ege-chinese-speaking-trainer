# Task 3 report — durable archive and review audio expiry

## Delivered

- Added `expire_recordings`, which acquires the SQLite immediate write lock, selects personal/archive then review metadata within one shared limit, deletes metadata, and queues deduplicated audio keys in the same transaction.
- Added personal archive keys to the existing account-deletion cleanup collection.
- Startup runs expiry before durable cleanup on a best-effort basis. The cleanup CLI skips startup cleanup and performs exactly one explicit `expire → process` sequence.
- Added regression coverage for expiry, shared limits, no empty jobs, deduplication, CLI sequencing/output/exit status, expired-route behavior, cleanup retry behavior, and account deletion of personal audio.

## TDD evidence

- Red: `.venv/bin/python -m unittest tests.unit.test_application_services tests.unit.test_storage_cleanup_command tests.integration.test_api_flows -v`
  - Failed as expected before implementation: `expire_recordings` was not importable and the CLI did not expose it.
- Green: `.venv/bin/python -m unittest tests.unit.test_application_services tests.unit.test_storage_cleanup_command tests.integration.test_api_flows -v`
  - Passed: 39 tests.
- Full verification: `make check`
  - Passed (exit 0): pre-commit hooks, JavaScript and Python unit/integration tests, coverage checks, and content validation.

## Review follow-up

- Added an end-to-end service-level regression: `expire_recordings` removes metadata and creates the job before a mocked storage adapter fails; the pending job retries and completes after the adapter recovers.
- Added startup best-effort regression: an expiry sweep exception is logged and does not prevent database initialization from returning.
- Follow-up focused verification passed: `.venv/bin/python -m unittest tests.unit.test_application_services tests.unit.test_storage_cleanup_command tests.integration.test_api_flows -v` (40 tests).
- Follow-up full verification passed: `make check` (exit 0).

## Commit

`feat: expire archived recordings after six months` (final hash is supplied with the handoff).

## Concerns

- No known functional concerns. PostgreSQL migration tests remain skipped when `TEST_DATABASE_URL` is unset, consistent with the project suite.
