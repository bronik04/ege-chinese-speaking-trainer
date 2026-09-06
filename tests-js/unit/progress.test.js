import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  LEGACY_PROGRESS_ACCOUNT_PREFIX,
  LEGACY_PROGRESS_GUEST_KEY,
  PROGRESS_ACCOUNT_PREFIX,
  PROGRESS_GUEST_KEY,
  ProgressContractError,
  defaultProgress,
  loadLocalProgress,
  mergeProgress,
  normalizeProgress,
  progressStorageKeys,
} from "../../frontend/js/shared/progress.js";

const fixtures = JSON.parse(readFileSync(
  new URL("../../tests/fixtures/progress_v1_migration_cases.json", import.meta.url),
  "utf8",
)).cases;

function activeRun(id = "active", overrides = {}) {
  return {
    id,
    variantId: "open-2026",
    variantLabel: "Открытый вариант 2026",
    mode: "practice",
    tasks: [2],
    completedTasks: [],
    currentTask: 2,
    phase: "idle",
    fastMode: false,
    startedAt: "2026-09-06T10:00:00Z",
    ...overrides,
  };
}

function completedRun(id = "run-1", completedAt = "2026-09-06T10:05:00Z", overrides = {}) {
  return {
    ...activeRun(id),
    completedTasks: [2],
    phase: "answer",
    status: "completed",
    completedAt,
    recordingsCount: 1,
    ...overrides,
  };
}

function validV2(overrides = {}) {
  return {
    version: 2,
    updatedAt: "2026-09-06T10:15:30Z",
    settings: { lastVariant: "open-2026", fastMode: false },
    runs: [completedRun()],
    activeRun: null,
    ...overrides,
  };
}

function fakeStorage(entries = {}, { failSet = false } = {}) {
  const values = new Map(Object.entries(entries));
  const calls = [];
  return {
    calls,
    getItem(key) {
      calls.push(["get", key]);
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      calls.push(["set", key]);
      if (failSet) throw new Error("quota");
      values.set(key, value);
    },
    removeItem(key) {
      calls.push(["remove", key]);
      values.delete(key);
    },
    value(key) {
      return values.get(key);
    },
  };
}

test("JavaScript migration matches every shared V1 fixture", () => {
  for (const fixture of fixtures) {
    const source = JSON.parse(JSON.stringify(fixture.input));
    if (fixture.expectedError) {
      assert.throws(
        () => normalizeProgress(source),
        error => error instanceof ProgressContractError && error.reason === fixture.expectedError,
        fixture.name,
      );
    } else {
      assert.deepEqual(normalizeProgress(source), fixture.expected, fixture.name);
    }
    assert.deepEqual(source, fixture.input, fixture.name);
  }
});

test("progress storage keys keep V1 and V2 guest and account scopes separate", () => {
  assert.equal(PROGRESS_GUEST_KEY, "egeChineseProgressV2");
  assert.equal(PROGRESS_ACCOUNT_PREFIX, "egeChineseProgressV2:user:");
  assert.equal(LEGACY_PROGRESS_GUEST_KEY, "egeChineseProgressV1");
  assert.equal(LEGACY_PROGRESS_ACCOUNT_PREFIX, "egeChineseProgressV1:user:");
  assert.deepEqual(progressStorageKeys(), {
    current: "egeChineseProgressV2",
    legacy: "egeChineseProgressV1",
  });
  assert.deepEqual(progressStorageKeys(7), {
    current: "egeChineseProgressV2:user:7",
    legacy: "egeChineseProgressV1:user:7",
  });
});

test("strict V2 rejects unknown fields, coercions and broken relationships", () => {
  const badRoot = validV2({ extra: true });
  const badSettings = validV2();
  badSettings.settings.extra = true;
  const badRun = validV2();
  badRun.runs[0].extra = true;
  const stringTask = validV2();
  stringTask.runs[0].tasks = ["2"];
  const foreignCurrent = validV2();
  foreignCurrent.runs[0].currentTask = 3;
  const backwards = validV2();
  backwards.runs[0].completedAt = "2026-09-06T09:59:00Z";
  const duplicate = validV2({ runs: [completedRun("same"), completedRun("same")] });
  for (const document of [badRoot, badSettings, badRun, stringTask, foreignCurrent, backwards, duplicate]) {
    assert.throws(() => normalizeProgress(document), ProgressContractError);
  }
  for (const version of [true, "2", 3]) {
    assert.throws(() => normalizeProgress({ ...validV2(), version }), ProgressContractError);
  }
});

test("strict V2 canonicalizes timestamps and unique task order", () => {
  const run = completedRun("exam", "2026-09-06T13:05:00+03:00", {
    mode: "exam",
    tasks: [3, 1, 2],
    completedTasks: [2, 3, 1],
    currentTask: 3,
    startedAt: "2026-09-06T13:00:00+03:00",
  });
  const result = normalizeProgress(validV2({
    updatedAt: "2026-09-06T13:15:30+03:00",
    runs: [run],
  }));
  assert.equal(result.updatedAt, "2026-09-06T10:15:30.000Z");
  assert.deepEqual(result.runs[0].tasks, [1, 2, 3]);
  assert.deepEqual(result.runs[0].completedTasks, [1, 2, 3]);
});

test("local V1 is deleted only after V2 is stored", () => {
  const keys = progressStorageKeys();
  const storage = fakeStorage({ [keys.legacy]: JSON.stringify({ version: 1 }) });
  const result = loadLocalProgress(keys, { storage });
  assert.equal(result.version, 2);
  assert.deepEqual(storage.calls.slice(-2).map(call => call.slice(0, 2)), [
    ["set", keys.current],
    ["remove", keys.legacy],
  ]);
  assert.equal(JSON.parse(storage.value(keys.current)).version, 2);
  assert.equal(storage.value(keys.legacy), undefined);
});

test("failed V2 write preserves V1 and returns the migrated in-memory copy", () => {
  const keys = progressStorageKeys(7);
  const storage = fakeStorage({ [keys.legacy]: JSON.stringify({ version: 1 }) }, { failSet: true });
  const errors = [];
  const result = loadLocalProgress(keys, { storage, onError: message => errors.push(message) });
  assert.equal(result.version, 2);
  assert.notEqual(storage.value(keys.legacy), undefined);
  assert.equal(storage.value(keys.current), undefined);
  assert.equal(errors.length, 1);
  assert.equal(storage.calls.some(call => call[0] === "remove"), false);
});

test("valid V2 wins without reading or deleting the legacy key", () => {
  const keys = progressStorageKeys();
  const current = normalizeProgress(validV2());
  const storage = fakeStorage({
    [keys.current]: JSON.stringify(current),
    [keys.legacy]: JSON.stringify({ version: 1 }),
  });
  assert.deepEqual(loadLocalProgress(keys, { storage }), current);
  assert.deepEqual(storage.calls, [["get", keys.current]]);
  assert.notEqual(storage.value(keys.legacy), undefined);
});

test("corrupt V2 returns a default and leaves both stored copies untouched", () => {
  const keys = progressStorageKeys();
  const storage = fakeStorage({
    [keys.current]: "{",
    [keys.legacy]: JSON.stringify({ version: 1 }),
  });
  const errors = [];
  assert.deepEqual(loadLocalProgress(keys, { storage, onError: message => errors.push(message) }), defaultProgress());
  assert.deepEqual(storage.calls, [["get", keys.current]]);
  assert.equal(storage.value(keys.current), "{");
  assert.notEqual(storage.value(keys.legacy), undefined);
  assert.equal(errors.length, 1);
});

test("mergeProgress gives local duplicates priority and keeps newer settings and active run", () => {
  const local = validV2({
    updatedAt: "2026-09-06T12:00:00Z",
    settings: { lastVariant: "local", fastMode: true },
    runs: [completedRun("same", "2026-09-06T12:00:00Z", { variantLabel: "Local" })],
    activeRun: activeRun("local-active"),
  });
  const remote = validV2({
    updatedAt: "2026-09-06T11:00:00Z",
    settings: { lastVariant: "remote", fastMode: false },
    runs: [
      completedRun("same", "2026-09-06T11:00:00Z", { variantLabel: "Remote" }),
      completedRun("remote", "2026-09-06T10:00:00Z"),
    ],
    activeRun: null,
  });
  const merged = mergeProgress(local, remote);
  assert.equal(merged.version, 2);
  assert.equal(merged.runs.length, 2);
  assert.equal(merged.runs.find(run => run.id === "same").variantLabel, "Local");
  assert.equal(merged.settings.lastVariant, "local");
  assert.equal(merged.activeRun.id, "local-active");
});

test("mergeProgress sorts newest first, truncates to 100 and lets the newer side clear activeRun", () => {
  const timestamp = offset => new Date(Date.parse("2026-09-06T10:00:00Z") + offset * 60_000).toISOString();
  const remoteRuns = Array.from({ length: 60 }, (_, index) => completedRun(`remote-${index}`, timestamp(index)));
  const localRuns = Array.from({ length: 60 }, (_, index) => completedRun(`local-${index}`, timestamp(index + 60)));
  const local = validV2({ updatedAt: timestamp(1), runs: localRuns, activeRun: activeRun("stale") });
  const remote = validV2({ updatedAt: timestamp(2), runs: remoteRuns, activeRun: null });
  const merged = mergeProgress(local, remote);
  assert.equal(merged.runs.length, 100);
  assert.equal(merged.runs[0].id, "local-59");
  assert.equal(merged.runs.at(-1).id, "remote-20");
  assert.equal(merged.activeRun, null);
});
