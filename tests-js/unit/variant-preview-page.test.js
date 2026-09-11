import assert from "node:assert/strict";
import test from "node:test";

import { createVariantPreviewPageController } from "../../frontend/js/catalog/variant-preview-page.js";

function materialFixture(overrides = {}) {
  return {
    id: "open-2026",
    label: "Официальный вариант 2026",
    source: "ФИПИ",
    year: 2026,
    kind: "full",
    taskNumber: null,
    totalMinutes: 14,
    tasks: {
      "1": { image: "assets/variants/a.webp", imageAlt: "Фото" },
      "2": { images: ["assets/variants/b.webp", "assets/variants/c.webp", "assets/variants/d.webp"] },
      "3": { images: ["assets/variants/e.webp", "assets/variants/f.webp"], imageLabels: ["Осень", "Зима"] },
    },
    ...overrides,
  };
}

function harness(request) {
  const states = [];
  let focused = 0;
  const controller = createVariantPreviewPageController({
    request,
    render: state => states.push(state),
    focus: () => { focused += 1; },
  });
  return { controller, states, focused: () => focused };
}

test("controller projects a successful response and focuses the page title", async () => {
  const subject = harness(async () => ({ material: materialFixture() }));

  await subject.controller.load();

  assert.deepEqual(subject.states.map(state => state.kind), ["loading", "success"]);
  assert.equal(subject.states[1].preview.tasks.length, 3);
  assert.equal(subject.states[1].preview.tasks[1].images.length, 3);
  assert.equal(subject.focused(), 1);
});

test("controller maps HTTP and payload failures to stable states", async t => {
  const cases = [
    { name: "forbidden", error: Object.assign(new Error("raw server message"), { status: 403 }), expected: "forbidden" },
    { name: "not found", error: Object.assign(new Error("raw server message"), { status: 404 }), expected: "not_found" },
    { name: "network", error: new Error("raw server HTML <script>"), expected: "network" },
  ];
  for (const item of cases) {
    await t.test(item.name, async () => {
      const subject = harness(async () => { throw item.error; });
      await subject.controller.load();
      assert.deepEqual(subject.states.map(state => state.kind), ["loading", item.expected]);
      assert.equal("message" in subject.states[1], false);
      assert.equal(subject.focused(), 1);
    });
  }

  const invalid = harness(async () => ({ material: materialFixture({ id: "" }) }));
  await invalid.controller.load();
  assert.deepEqual(invalid.states.map(state => state.kind), ["loading", "invalid_material"]);
  assert.equal(invalid.focused(), 1);
});

test("retry starts a fresh request", async () => {
  let attempts = 0;
  const subject = harness(async () => {
    attempts += 1;
    if (attempts === 1) throw new Error("offline");
    return { material: materialFixture() };
  });

  await subject.controller.load();
  await subject.controller.retry();

  assert.equal(attempts, 2);
  assert.deepEqual(subject.states.map(state => state.kind), ["loading", "network", "loading", "success"]);
  assert.equal(subject.focused(), 2);
});

test("an older response cannot replace or focus over the newest load", async () => {
  let resolveFirst;
  let resolveSecond;
  const first = new Promise(resolve => { resolveFirst = resolve; });
  const second = new Promise(resolve => { resolveSecond = resolve; });
  let requests = 0;
  const subject = harness(() => {
    requests += 1;
    return requests === 1 ? first : second;
  });

  const oldLoad = subject.controller.load();
  const currentLoad = subject.controller.load();
  resolveSecond({ material: materialFixture({ id: "newest", label: "Новый" }) });
  await currentLoad;
  resolveFirst({ material: materialFixture({ id: "old", label: "Старый" }) });
  await oldLoad;

  assert.deepEqual(subject.states.map(state => state.kind), ["loading", "loading", "success"]);
  assert.equal(subject.states.at(-1).preview.id, "newest");
  assert.equal(subject.focused(), 1);
});

test("an older rejection is ignored after a newer success", async () => {
  let rejectFirst;
  const first = new Promise((_, reject) => { rejectFirst = reject; });
  let requests = 0;
  const subject = harness(() => {
    requests += 1;
    return requests === 1 ? first : Promise.resolve({ material: materialFixture({ id: "newest" }) });
  });

  const oldLoad = subject.controller.load();
  await subject.controller.load();
  rejectFirst(new Error("late failure"));
  await oldLoad;

  assert.deepEqual(subject.states.map(state => state.kind), ["loading", "loading", "success"]);
  assert.equal(subject.focused(), 1);
});
