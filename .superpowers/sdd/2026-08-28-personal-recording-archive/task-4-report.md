# Task 4 — registered upload and personal archive history UI

## Red / green verification

- Red: `npm test && npm exec playwright test tests-e2e/student-teacher.spec.js -- --grep 'personal archive'` — failed as expected because `account-personal-recordings-controller.js` did not exist.
- Green: `npm test && npm exec playwright test tests-e2e/student-teacher.spec.js -- --grep 'personal archive'` — passed: 14 JavaScript unit tests and the `personal archive` Playwright scenario.
- Required verification: `make check` — passed (pre-commit checks, 14 JavaScript unit tests, 110 Python unit tests, and 93 integration tests; 2 PostgreSQL tests skipped because `TEST_DATABASE_URL` is not configured).
- UI verification: `make test-e2e` — passed (25 Playwright scenarios).

## Delivered behaviour

- Registered students archive every completed answer recording after a run; guests keep recordings only in the current tab and make no archive upload request.
- Archive list and private stream URLs are rendered in the history modal with escaped metadata and a visible expiry date.
- Duplicate archive responses are transparent, and the result screen reports a non-blocking warning if archive sync fails.
- Clearing local history explicitly preserves server-side archived audio.

## Concerns

- The existing API requires `questionNumber` for every archive row. The UI retains task-one question positions and uses position `1` for the single answer of tasks two and three, matching the current API uniqueness contract.

## Commit

`feat: show personal recording archive` (final hash is supplied with the handoff).
