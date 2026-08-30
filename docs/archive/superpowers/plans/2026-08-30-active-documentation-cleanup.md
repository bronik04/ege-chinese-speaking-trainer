# Active Documentation Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every active project guide describe the current SQLite-only FastAPI application and move completed design history out of the operational documentation surface.

**Architecture:** Treat ADRs as immutable historical records, active guides as authoritative current state, and old Superpowers plans/specs as an explicitly labelled archive. Add a focused regression test for the exact stale runtime references that have already caused contradictions.

**Tech Stack:** Markdown, Python unittest, repository-hygiene checks, Git

**Spec:** `docs/superpowers/specs/2026-08-30-technical-removal-cleanup-design.md`

## Global Constraints

- Do not rewrite historical ADR bodies; ADR 0004 remains the authority that supersedes PostgreSQL support.
- Do not claim support for a file, worker, Compose profile, database engine, or command that is absent.
- Preserve instructions for SQLite, S3/R2, SMTP, backup/restore, review requests, personal recordings, and cleanup.
- Historical plans/specs remain available under `docs/archive/superpowers/` and are explicitly non-authoritative.
- Keep the current cleanup spec and the three 2026-08-30 implementation plans active until all cleanup packages finish.
- Run `make check` before declaring this package complete.

---

### Task 1: Add an active-documentation regression guard

**Files:**
- Modify: `tests/unit/test_repository_hygiene.py`

**Interfaces:**
- Consumes: authoritative current guides listed below
- Produces: `RepositoryHygieneTest.test_active_docs_do_not_describe_removed_runtimes`

- [x] **Step 1: Write the failing test**

Add this method:

```python
def test_active_docs_do_not_describe_removed_runtimes(self):
    root = Path(__file__).resolve().parents[2]
    active = (
        "README.md",
        "DEVELOPMENT.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/README.md",
        "docs/architecture.md",
        "docs/agent-guidelines.md",
        "docs/runbooks/backup-restore.md",
        "docs/runbooks/incident-response.md",
    )
    forbidden = (
        "legacy/README.md",
        "compose.scale.yml",
        "scripts.transcription_worker",
        "docs/runbooks/transcription-worker.md",
        "src/trainer/workers/",
        "src/trainer/infrastructure/database/postgres.py",
        "scripts.postgres_restore_smoke",
    )
    for relative in active:
        source = (root / relative).read_text(encoding="utf-8")
        for marker in forbidden:
            self.assertNotIn(marker, source, f"{relative}: {marker}")
```

- [x] **Step 2: Run the test and verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_repository_hygiene.RepositoryHygieneTest.test_active_docs_do_not_describe_removed_runtimes -v`

Expected: FAIL on existing references in README, DEVELOPMENT, AGENTS, CLAUDE, architecture, and runbooks.

- [x] **Step 3: Commit the failing guard with the documentation changes in Task 2**

Do not commit the red test alone; it becomes green in the next task.

---

### Task 2: Rewrite active guides to match the current runtime

**Files:**
- Modify: `README.md`
- Modify: `DEVELOPMENT.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/agent-guidelines.md`
- Modify: `docs/runbooks/backup-restore.md`
- Modify: `docs/runbooks/incident-response.md`
- Modify: `tests/unit/test_repository_hygiene.py`

**Interfaces:**
- Consumes: ADR 0004, `compose.yml`, `.env.example`, `Makefile`, `scripts/`, and the actual `src/trainer` tree
- Produces: current operational documentation with no absent-runtime instructions

- [x] **Step 1: Replace the architecture summary**

Ensure `docs/architecture.md` states these exact current facts:

```markdown
- FastAPI через `asgi.py` — единственный HTTP runtime.
- SQLite в WAL-режиме — единственный поддерживаемый движок БД.
- Новые изменения схемы добавляются Alembic-ревизиями после замороженного SQLite baseline 1–7.
- Закрытые файлы хранятся локально или в S3/R2; почта использует SMTP либо приватный outbox.
- Фоновые операции хранения выполняются командой `python -m scripts.cleanup_storage`.
```

Remove current-state tree entries for `legacy/` and `src/trainer/workers/`, references to PDF/OpenAI
infrastructure, and the future migration step that still proposes SQLite/PostgreSQL unification.

- [x] **Step 2: Correct DEVELOPMENT and runbooks**

In `DEVELOPMENT.md`:

- remove the transcription section and missing runbook link;
- replace “SQLite и PostgreSQL” with “SQLite и Alembic”;
- remove `DATABASE_URL`, `TEST_DATABASE_URL`, `compose.scale.yml`, `pg_dump`, and PostgreSQL smoke commands;
- retain the warning not to delete legacy assignment tables manually;
- document `python -m scripts.cleanup_storage` as the maintenance command;
- make the CI description match `.github/workflows/ci.yml` exactly.

In `backup-restore.md`, keep only SQLite plus local/S3 asset backup. Replace assignment-specific wording with:

```markdown
`assignment-assets/` сохраняет историческое физическое имя и содержит приватные snapshot-изображения;
каталог обязателен при восстановлении экземпляра, на котором создавались review requests.
```

Delete the PostgreSQL restore section. In `incident-response.md`, compare request time with app and proxy
logs; mention cleanup command output instead of PostgreSQL/worker logs.

- [x] **Step 3: Correct contributor and agent guides**

Update `AGENTS.md` and `CLAUDE.md` so they point only to current directories and responsibilities. Preserve
the dependency direction `API → domain → infrastructure interfaces`, but remove groups/assignments/OpenAI
from the list of active domain/infrastructure examples. Replace dual-database guidance with:

```markdown
Для схемы БД добавляйте новую Alembic-ревизию и проверяйте чистую, обновляемую и повторно обновляемую SQLite-базу.
```

In `docs/agent-guidelines.md`, remove transcription from the security-sensitive current zones.

- [x] **Step 4: Correct README indexes**

Remove the transcription-worker reference from `README.md` and `docs/README.md`. Add one archive entry:

```markdown
- [Архив проектных планов](archive/superpowers/) — исторические документы, не описывающие текущее состояние системы.
```

- [x] **Step 5: Run the documentation guard**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_repository_hygiene -v
rg -n "legacy/README\.md|compose\.scale\.yml|scripts\.transcription_worker|transcription-worker\.md|src/trainer/workers/|database/postgres\.py|scripts\.postgres_restore_smoke" README.md DEVELOPMENT.md AGENTS.md CLAUDE.md docs --glob '!docs/archive/**' --glob '!docs/superpowers/**' --glob '!docs/decisions/**'
```

Expected: tests pass and `rg` returns no matches.

- [x] **Step 6: Commit**

```bash
git add README.md DEVELOPMENT.md AGENTS.md CLAUDE.md docs/README.md docs/architecture.md docs/agent-guidelines.md docs/runbooks tests/unit/test_repository_hygiene.py
git commit -m "docs: align active guides with current runtime"
```

---

### Task 3: Archive completed Superpowers documents

**Files:**
- Create: `docs/archive/superpowers/README.md`
- Move: completed files from `docs/superpowers/plans/` to `docs/archive/superpowers/plans/`
- Move: completed files from `docs/superpowers/specs/` to `docs/archive/superpowers/specs/`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: all plans/specs dated before 2026-08-30
- Produces: an explicit historical archive; current cleanup spec/plans remain under `docs/superpowers/`

- [x] **Step 1: Create the archive index**

```markdown
# Архив проектных документов

Здесь хранятся завершённые спецификации и планы прошлых состояний проекта. Они нужны для истории решений,
но не являются инструкцией по текущей архитектуре, запуску или эксплуатации. Актуальные сведения находятся
в `README.md`, `DEVELOPMENT.md`, `docs/architecture.md`, ADR и runbooks.
```

- [x] **Step 2: Move only completed pre-cleanup documents**

Move every file dated before `2026-08-30` from `docs/superpowers/plans/` and `docs/superpowers/specs/` into
the matching archive subdirectory. Do not move:

```text
docs/superpowers/specs/2026-08-30-technical-removal-cleanup-design.md
docs/superpowers/plans/2026-08-30-retired-backend-removal.md
docs/superpowers/plans/2026-08-30-active-documentation-cleanup.md
docs/superpowers/plans/2026-08-30-frontend-code-pruning.md
```

- [x] **Step 3: Verify the archive boundary**

Run:

```bash
find docs/superpowers/plans docs/superpowers/specs -type f -maxdepth 1 -print | sort
find docs/archive/superpowers -type f -print | sort
```

Expected: active directories contain only the four current cleanup documents; the archive contains its
README plus every earlier plan/spec.

- [x] **Step 4: Commit**

```bash
git add docs/archive docs/superpowers docs/README.md
git commit -m "docs: archive completed implementation records"
```

---

### Task 4: Complete documentation verification

**Files:**
- Modify only if verification exposes an incorrect current-state statement

**Interfaces:**
- Consumes: Tasks 1–3
- Produces: a passing documentation cleanup package

- [x] **Step 1: Check referenced current files exist**

Run this focused script:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

root = Path.cwd()
required = (
    "asgi.py",
    "compose.yml",
    "scripts/cleanup_storage.py",
    "scripts/backup.py",
    "docs/runbooks/backup-restore.md",
    "docs/runbooks/recording-retention.md",
    "docs/runbooks/incident-response.md",
)
missing = [item for item in required if not (root / item).is_file()]
raise SystemExit(f"missing documented files: {missing}" if missing else 0)
PY
```

Expected: exit 0.

- [x] **Step 2: Run mandatory verification**

Run: `make check`

Expected: all hooks and tests pass.

- [x] **Step 3: Review changed documentation only**

Run:

```bash
git diff --check HEAD~2..HEAD
git status --short
```

Expected: no whitespace errors; only the pre-existing `.superpowers/brainstorm/` may remain untracked.
