# Unified Interface Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Привести все экраны приложения к визуальному языку новой главной и заменить металлические интерактивные поверхности единой плоской кремово-бордово-золотой палитрой.

**Architecture:** Общие цветовые состояния, поверхности, фокус и кнопочные компоненты задаются один раз в `frontend/styles/base.css`; CSS конкретных страниц отвечает только за их сетки и композицию. Существующие HTML id, JavaScript-обработчики и HTTP-контракты сохраняются; разметка меняется только для создания ясных семантических групп кабинета, истории и редактора.

**Tech Stack:** Vanilla HTML/CSS/JavaScript, FastAPI static delivery, Node test runner, ESLint, Playwright Chromium.

**Spec:** `docs/superpowers/specs/2026-08-29-unified-interface-design-system-design.md`

## Global Constraints

- Главная, тренажёр, результаты, авторизация, каталог и справочник сохраняют текущую композицию.
- Кабинет преподавателя остаётся большим модальным рабочим пространством; отдельная страница кабинета не создаётся.
- Все кнопки, вкладки и фильтры используют кремовый обычный фон, светло-золотой hover и бордовое выбранное состояние.
- Опасные действия сохраняют отдельную красную семантику.
- Металлические золотые градиенты на интерактивных элементах запрещены; декоративные линии и неинтерактивные статусы могут оставаться золотыми.
- API, роли, таймеры, запись аудио, хранение, публикация и правила оценивания не меняются.
- Интерактивные элементы на мобильном имеют высоту не меньше 44 CSS px.
- Десктоп и ширина 390 px не имеют горизонтального переполнения.
- `prefers-reduced-motion`, клавиатурный фокус, `aria-live`, подписи полей и управление модальными окнами сохраняются.
- Существующие незакоммиченные изменения `frontend/styles/base.css` и `tests-e2e/reference.spec.js`, которые фиксируют пробную кремовую кнопку главной, считаются началом Task 1 и не должны быть потеряны.

---

### Task 1: Общая интерактивная палитра и основные действия

**Files:**
- Modify: `frontend/styles/base.css:1-34,151-160,460-572`
- Modify: `tests-e2e/reference.spec.js:49-82`

**Interfaces:**
- Consumes: существующие токены `--cream`, `--gold-pale`, `--crimson-deep`, `--crimson`, `--paper`.
- Produces: CSS-токены `--action-bg`, `--action-text`, `--action-hover-bg`, `--action-active-bg`, `--action-active-text`, `--action-border`; общие состояния `.primary-btn`, `.secondary-btn`, `.wide`, `.gold-btn`.

- [ ] **Step 1: Расширить браузерный тест до главной, тренажёра и авторизации**

В `tests-e2e/reference.spec.js` сохранить существующий тест главной и добавить отдельный тест реальных primary actions:

```js
test("primary actions share the flat cream and gold palette", async ({ page }) => {
  await page.goto("/");
  const homeAction = page.locator('.home-screen [data-start="exam"]');
  await expect(homeAction).toBeEnabled();
  await expect(homeAction).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await expect(homeAction).toHaveCSS("background-image", "none");
  await expect(homeAction).toHaveCSS("color", "rgb(92, 14, 14)");

  await page.locator('[data-start="1"]').click();
  const runnerAction = page.locator("#mainActionBtn");
  await expect(runnerAction).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await expect(runnerAction).toHaveCSS("background-image", "none");

  await page.locator("#exitBtn").click();
  await page.locator("#authButton").click();
  const authAction = page.locator("#authSubmitBtn");
  await expect(authAction).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await expect(authAction).toHaveCSS("background-image", "none");
  await authAction.hover();
  await expect(authAction).toHaveCSS("background-color", "rgb(232, 211, 138)");
});
```

- [ ] **Step 2: Запустить тест и подтвердить правильное падение**

Run:

```bash
npx playwright test tests-e2e/reference.spec.js -g "primary actions share the flat cream and gold palette"
```

Expected: FAIL на `#mainActionBtn` или `#authSubmitBtn`, потому что текущие scoped overrides всё ещё задают `var(--gold-metal)`.

- [ ] **Step 3: Добавить токены и централизованные состояния**

В `:root` файла `frontend/styles/base.css` добавить:

```css
--action-bg: var(--cream);
--action-text: var(--crimson-deep);
--action-hover-bg: var(--gold-pale);
--action-active-bg: var(--crimson-deep);
--action-active-text: var(--cream);
--action-border: rgba(139, 26, 26, .18);
```

После базовых `.primary-btn`/`.secondary-btn` разместить итоговые общие состояния и удалить конкурирующие золотые overrides для `.runner-screen .wide`, `.result-screen .wide`, `#authModal .wide` и `.home-screen .gold-btn`:

```css
.primary-btn,
.secondary-btn,
.wide,
.gold-btn {
  border: 1px solid var(--action-border);
  background: var(--action-bg);
  color: var(--action-text);
  box-shadow: none;
  transition: background-color .16s, border-color .16s, color .16s;
}

.primary-btn:hover:not(:disabled),
.secondary-btn:hover:not(:disabled),
.wide:hover:not(:disabled),
.gold-btn:hover:not(:disabled) {
  border-color: var(--gold);
  background: var(--action-hover-bg);
  color: var(--action-text);
  filter: none;
}

.primary-btn:active:not(:disabled),
.secondary-btn:active:not(:disabled),
.wide:active:not(:disabled),
.gold-btn:active:not(:disabled) {
  background: var(--action-active-bg);
  color: var(--action-active-text);
  box-shadow: none;
}
```

Сохранить текущие размеры и `border-radius` scoped-компонентов. `.danger-btn` и `.danger-link` не включать в общий набор.

- [ ] **Step 4: Запустить целевой тест**

Run:

```bash
npx playwright test tests-e2e/reference.spec.js -g "home exam action|primary actions share"
```

Expected: 2 tests PASS.

- [ ] **Step 5: Запустить линтер и закоммитить**

Run:

```bash
npm run lint
```

Expected: ESLint PASS.

Commit:

```bash
git add frontend/styles/base.css tests-e2e/reference.spec.js
git commit -m "style: unify primary action colors"
```

---

### Task 2: Вкладки, фильтры, элементы выбора и публичные страницы

**Files:**
- Modify: `frontend/styles/base.css:82-106,460-522,557-588`
- Modify: `frontend/styles/pages/reference.css:87-135`
- Modify: `frontend/styles/pages/variants.css:1-5`
- Modify: `tests-e2e/reference.spec.js:3-33`
- Modify: `tests-e2e/variants-catalog.spec.js:57-73`

**Interfaces:**
- Consumes: action tokens из Task 1.
- Produces: единые flat-state правила для utility controls `.account-btn`, `.sound-toggle`, `.back-btn`, `.text-btn`, `.auth-link`, `.modal-close`; choice controls `.task-card`, `.photo-choice`, `.auth-tabs button`, `.step-pill`, `.project-select-trigger`, `.project-select-option`, `.reference-tab`, `.copy-phrase`, `.year-filter`, `.variant-open`, `.material-row`.

- [ ] **Step 1: Добавить падающие проверки выбранных и hover-состояний**

В тест справочника добавить:

```js
const activeReferenceTab = page.locator(".reference-tab.active");
await expect(activeReferenceTab).toHaveCSS("background-color", "rgb(92, 14, 14)");
await expect(activeReferenceTab).toHaveCSS("background-image", "none");
await expect(activeReferenceTab).toHaveCSS("color", "rgb(244, 236, 219)");
const copyButton = page.locator(".copy-phrase").first();
await expect(copyButton).toHaveCSS("background-color", "rgb(244, 236, 219)");
await expect(copyButton).toHaveCSS("background-image", "none");
await copyButton.hover();
await expect(copyButton).toHaveCSS("background-color", "rgb(232, 211, 138)");
```

В тест главной `home uses horizontal motto...` добавить проверки utility и choice controls:

```js
await expect(page.locator("#authButton")).toHaveCSS("background-color", "rgb(244, 236, 219)");
const taskChoice = page.locator('[data-start="1"]');
await expect(taskChoice).toHaveCSS("background-color", "rgb(244, 236, 219)");
await taskChoice.hover();
await expect(taskChoice).toHaveCSS("background-color", "rgb(232, 211, 138)");
await page.locator("#authButton").click();
await expect(page.locator("#loginTab")).toHaveCSS("background-color", "rgb(92, 14, 14)");
await expect(page.locator("#loginTab")).toHaveCSS("background-image", "none");
```

В гостевой тест каталога добавить:

```js
const activeYear = page.locator(".year-filter.active");
await expect(activeYear).toHaveCSS("background-color", "rgb(92, 14, 14)");
await expect(activeYear).toHaveCSS("background-image", "none");
const openVariant = page.locator(".variant-open").first();
await expect(openVariant).toHaveCSS("background-color", "rgb(244, 236, 219)");
await openVariant.hover();
await expect(openVariant).toHaveCSS("background-color", "rgb(232, 211, 138)");
```

- [ ] **Step 2: Запустить два теста и подтвердить падение на металлических градиентах**

Run:

```bash
npx playwright test tests-e2e/reference.spec.js tests-e2e/variants-catalog.spec.js -g "reference library|home uses horizontal motto|guest catalog"
```

Expected: FAIL на active reference/year или copy/open controls, потому что текущий CSS задаёт `--gold-metal-*`.

- [ ] **Step 3: Реализовать общие состояния элементов выбора**

В `frontend/styles/base.css` определить общий паттерн без изменения геометрии:

```css
:where(.account-btn, .sound-toggle, .back-btn, .text-btn, .auth-link, .modal-close,
       .task-card, .photo-choice, .auth-tabs button, .step-pill,
       .project-select-trigger, .project-select-option, .material-row) {
  border-color: var(--action-border);
  background: var(--action-bg);
  color: var(--action-text);
  background-image: none;
  box-shadow: none;
}

:where(.account-btn, .sound-toggle, .back-btn, .text-btn, .auth-link, .modal-close,
       .task-card, .photo-choice, .auth-tabs button, .step-pill,
       .project-select-trigger, .project-select-option, .material-row):hover:not(:disabled) {
  background: var(--action-hover-bg);
  color: var(--action-text);
}

:where(.photo-choice.selected, .auth-tabs button.active, .step-pill.active,
       .project-select-option[aria-selected="true"], .material-row.selected) {
  background: var(--action-active-bg);
  color: var(--action-active-text);
  box-shadow: none;
}
```

Сохранить подчёркивание и компактный размер `.text-btn`/`.auth-link`, круглую геометрию `.sound-toggle`/`.modal-close`, карточную геометрию `.task-card`/`.photo-choice` и pill-геометрию `.account-btn`/tabs/filters. Для `.account-btn.signed-in` оставить status-dot, но не возвращать бордовую заливку самой кнопке.

В `reference.css` и `variants.css` заменить металлические правила интерактивных компонентов плоскими:

```css
.reference-tab.active,
.year-filter.active {
  color: var(--action-active-text);
  background: var(--action-active-bg);
  box-shadow: none;
}

.copy-phrase,
.variant-open {
  color: var(--action-text);
  background: var(--action-bg);
  box-shadow: none;
}

.copy-phrase:hover,
.variant-open:hover {
  color: var(--action-text);
  background: var(--action-hover-bg);
  filter: none;
}
```

Проверить, что цифры внутри активной `.reference-tab` наследуют кремовый текст, а не возвращаются к бордовому отдельным более специфичным правилом.

- [ ] **Step 4: Запустить тесты справочника и каталога**

Run:

```bash
npx playwright test tests-e2e/reference.spec.js tests-e2e/variants-catalog.spec.js
```

Expected: все тесты в обоих файлах PASS.

- [ ] **Step 5: Закоммитить публичные интерактивные состояния**

```bash
git add frontend/styles/base.css frontend/styles/pages/reference.css frontend/styles/pages/variants.css tests-e2e/reference.spec.js tests-e2e/variants-catalog.spec.js
git commit -m "style: flatten interactive choice states"
```

---

### Task 3: Личный кабинет, история и кабинет преподавателя

**Files:**
- Modify: `frontend/pages/index.html:101-208`
- Modify: `frontend/styles/base.css:273-376,557-594`
- Modify: `frontend/js/account/account-view.js:1-27`
- Modify: `tests-js/unit/views.test.js`
- Modify: `tests-e2e/account-workflows.spec.js:131-159`
- Modify: `tests-e2e/student-teacher.spec.js:280-336`

**Interfaces:**
- Consumes: action tokens и общие control states из Tasks 1–2; существующие id `teacherModal`, `teacherTitle`, `reviewRequestFilters`, `teacherReviewRequests`, `progressModal`, `historyList`, `personalRecordingsList`.
- Produces: классы `.dialog-heading`, `.teacher-workspace`, `.teacher-request-heading`, `.teacher-request-status`, `.history-sections`; обновлённая карточная разметка `teacherReviewRequestsMarkup(requests)` без изменения аргумента и возвращаемого типа `string`.

- [ ] **Step 1: Зафиксировать новые семантические группы unit-тестом**

В `tests-js/unit/views.test.js` расширить существующий тест teacher markup:

```js
const teacherMarkup = teacherReviewRequestsMarkup([{
  id: 9,
  studentName: "Student",
  studentEmail: "student@example.test",
  kind: "task",
  tasks: [2],
  status: "queued",
  submittedAt: 1_789_000_000,
  total: null,
  maximum: 7,
  recordings: [],
  scores: {},
}]);
assert.match(teacherMarkup, /class="teacher-request-heading"/);
assert.match(teacherMarkup, /class="teacher-request-status"/);
assert.match(teacherMarkup, /class="review-form"/);
```

- [ ] **Step 2: Добавить браузерные проверки модальных рабочих областей**

В `tests-e2e/account-workflows.spec.js` после открытия teacher modal добавить:

```js
await expect(teacherPage.locator("#teacherModal .teacher-dialog")).toHaveCSS("border-radius", "16px");
await expect(teacherPage.locator("#teacherModal .teacher-materials-entry")).toHaveCSS("border-radius", "16px");
await expect(teacherPage.locator("#reviewRequestFilters")).toHaveCSS("border-radius", "12px");
await teacherPage.setViewportSize({ width: 390, height: 844 });
expect(await teacherPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
```

В owner-scoring test после появления заявки добавить:

```js
const requestCard = teacherPage.locator(".teacher-review-request-card").first();
await expect(requestCard).toHaveCSS("border-radius", "12px");
await expect(requestCard.locator(".primary-btn")).toHaveCSS("background-color", "rgb(244, 236, 219)");
await expect(requestCard.locator(".primary-btn")).toHaveCSS("background-image", "none");
```

- [ ] **Step 3: Запустить unit и целевые E2E-тесты, подтвердить падение**

Run:

```bash
node --test tests-js/unit/views.test.js
npx playwright test tests-e2e/account-workflows.spec.js tests-e2e/student-teacher.spec.js -g "student and owner cabinets|owner scores queued review"
```

Expected: unit FAIL из-за отсутствующих классов; E2E FAIL на скруглениях teacher/filter/request card.

- [ ] **Step 4: Обновить безопасную разметку без изменения id**

В `frontend/pages/index.html` сгруппировать заголовки teacher/progress dialogs:

```html
<header class="dialog-heading">
  <p class="eyebrow">Кабинет преподавателя</p>
  <h2 id="teacherTitle">Очередь разбора</h2>
  <p class="auth-lede">Прослушивайте отправленные записи и сохраняйте баллы по критериям.</p>
</header>
```

Рабочие секции teacher dialog обернуть в `<div class="teacher-workspace">`, а блоки history и personal recordings — в `<div class="history-sections">`. Не перемещать кнопки закрытия и не менять id форм/контейнеров.

В `frontend/js/account/account-view.js` заменить шапку динамической карточки на:

```js
<header class="teacher-request-heading"><div><p class="eyebrow">${escapeHtml(request.studentName)}</p><h3>${escapeHtml(request.studentEmail)}</h3><span>${request.kind === "attempt" ? "Вся попытка" : "Одно задание"} · задания ${request.tasks.join(", ")}</span><small>${formatHistoryDate(request.submittedAt * 1000)}</small></div><b class="teacher-request-status">${request.status === "reviewed" ? `${request.total}/${request.maximum}` : "На разборе"}</b></header>
```

Сохранить существующее escaping, `data-review-request`, `data-review-tasks`, audio URLs и имена score inputs.

- [ ] **Step 5: Реализовать карточную компоновку кабинетов**

В `frontend/styles/base.css` добавить shared dialog shell для трёх modal ids и scoped layout:

```css
:where(#authModal, #teacherModal, #progressModal) .auth-dialog {
  border: 1px solid var(--hairline);
  border-radius: var(--radius-lg);
  background: #fff;
  box-shadow: 0 24px 75px rgba(50, 12, 9, .28);
}

#teacherModal .teacher-dialog { width: min(1120px, 100%); padding: 38px; }
.dialog-heading { padding-right: 54px; }
.teacher-workspace { display: grid; gap: 24px; margin-top: 26px; }
.teacher-materials-entry { border: 0; border-radius: var(--radius-lg); box-shadow: inset 0 0 0 1px rgba(201,162,39,.28); }
.submission-filters { padding: 16px; border: 1px solid var(--hairline); border-radius: var(--radius-md); background: var(--paper); }
.teacher-review-request-card { overflow: hidden; border-color: var(--hairline); border-radius: var(--radius-md); box-shadow: var(--card-shadow); }
.teacher-request-status { padding: 7px 11px; border-radius: var(--radius-pill); color: var(--crimson-deep); background: var(--cream); }
.review-form { background: #fdfaf2; }
.history-sections { display: grid; gap: 20px; }
.history-item, .personal-recording-item { padding: 16px; border: 1px solid var(--hairline); border-radius: var(--radius-md); background: var(--paper); }
```

Добавить mobile rules для `max-width: 700px`: teacher dialog padding 24px 16px, `.submission-filters { grid-template-columns: 1fr; }`, headings and request headers stack, buttons/forms stay within width.

- [ ] **Step 6: Запустить unit и teacher/account E2E**

Run:

```bash
npm test
npx playwright test tests-e2e/account-workflows.spec.js tests-e2e/student-teacher.spec.js
```

Expected: все JS unit tests и оба E2E-файла PASS.

- [ ] **Step 7: Закоммитить кабинеты**

```bash
git add frontend/pages/index.html frontend/styles/base.css frontend/js/account/account-view.js tests-js/unit/views.test.js tests-e2e/account-workflows.spec.js tests-e2e/student-teacher.spec.js
git commit -m "style: redesign account and teacher workspaces"
```

---

### Task 4: Редактор материалов

**Files:**
- Modify: `frontend/pages/variant-editor.html:20-73`
- Modify: `frontend/styles/pages/variant-editor.css:1-47`
- Modify: `tests-e2e/variants-catalog.spec.js:74-146`

**Interfaces:**
- Consumes: action tokens и shared inputs/buttons из Tasks 1–2; существующие ids и `data-task-editor`, `data-asset`, `data-asset-status`.
- Produces: обновлённые layout classes `.editor-card`, `.editor-section-card`; прежние DOM ids и форма `#materialForm` остаются совместимыми с `frontend/js/materials/material-editor.js`.

- [ ] **Step 1: Добавить desktop и mobile проверки редактора**

В registered-author test после `page.goto("/variant-editor.html")` добавить:

```js
await expect(page.locator(".materials-sidebar")).toHaveCSS("border-radius", "16px");
await expect(page.locator(".editor-panel")).toHaveCSS("border-radius", "16px");
await expect(page.locator("#newMaterialBtn")).toHaveCSS("background-color", "rgb(244, 236, 219)");
await expect(page.locator("#newMaterialBtn")).toHaveCSS("background-image", "none");
await expect(page.locator(".task-editor").first()).toHaveCSS("border-radius", "12px");

await page.setViewportSize({ width: 390, height: 844 });
expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
const sidebarBox = await page.locator(".materials-sidebar").boundingBox();
const editorBox = await page.locator(".editor-panel").boundingBox();
expect(Math.abs(sidebarBox.x - editorBox.x)).toBeLessThan(2);
expect(editorBox.y).toBeGreaterThan(sidebarBox.y);
await expect(page.locator("#saveMaterialBtn")).toHaveCSS("min-height", "44px");
```

- [ ] **Step 2: Запустить целевой тест и подтвердить падение legacy-редактора**

Run:

```bash
npx playwright test tests-e2e/variants-catalog.spec.js -g "registered user publishes"
```

Expected: FAIL на `border-radius` sidebar/editor/task section.

- [ ] **Step 3: Добавить только семантические layout classes**

В `frontend/pages/variant-editor.html` добавить класс `editor-card` к `.materials-sidebar` и `.editor-panel`, класс `editor-section-card` к `.editor-section` и каждому `.task-editor`. Не менять ids, порядок fields, `data-task-editor`, `data-asset` или buttons.

Пример:

```html
<aside class="materials-sidebar editor-card">
```

```html
<section class="task-editor editor-section-card" data-task-editor="1">
```

- [ ] **Step 4: Переписать page CSS как композицию общей системы**

В `frontend/styles/pages/variant-editor.css` сохранить двухколоночный layout, но заменить legacy surfaces:

```css
.editor-layout { display: grid; grid-template-columns: 310px minmax(0, 1fr); gap: 24px; align-items: start; }
.editor-card { overflow: hidden; border: 1px solid var(--hairline); border-radius: var(--radius-lg); background: #fff; box-shadow: var(--card-shadow); }
.materials-sidebar { position: sticky; top: 18px; padding: 22px; }
.my-material { min-height: 64px; padding: 12px 14px; border: 1px solid var(--hairline); border-radius: var(--radius-md); background: var(--paper); }
.my-material:hover { border-color: var(--gold); background: var(--action-hover-bg); }
.my-material.active { border-color: var(--crimson-deep); color: var(--action-active-text); background: var(--action-active-bg); }
.editor-panel { padding-bottom: 20px; }
.editor-section-card { margin: 18px; padding: 24px; border: 1px solid var(--hairline); border-radius: var(--radius-md); background: #fff; }
.editor-panel :where(input, textarea, .project-select-trigger) { min-height: 44px; border-color: var(--hairline); border-radius: var(--radius-sm); background: var(--paper); }
.asset-field { border-color: rgba(139,26,26,.24); border-radius: var(--radius-md); background: #fdfaf2; }
.editor-actions { margin: 18px; border-radius: var(--radius-md); background: var(--paper); }
```

Убрать page-specific `publish-btn` gold/crimson override: публикация использует общий primary action, архивирование остаётся danger.

На `max-width: 900px` использовать одну колонку и static sidebar. На `max-width: 700px` убрать внешние horizontal padding, сделать формы одноколоночными и задать `.editor-actions > button { width: 100%; min-height: 44px; }`.

- [ ] **Step 5: Запустить editor/catalog тест и линтер**

Run:

```bash
npx playwright test tests-e2e/variants-catalog.spec.js
npm run lint
```

Expected: все catalog/editor E2E tests и ESLint PASS.

- [ ] **Step 6: Закоммитить редактор**

```bash
git add frontend/pages/variant-editor.html frontend/styles/pages/variant-editor.css tests-e2e/variants-catalog.spec.js
git commit -m "style: align material editor with home design"
```

---

### Task 5: Адаптив, остаточные состояния и полная приёмка

**Files:**
- Modify: `frontend/styles/base.css`
- Modify: `frontend/styles/pages/reference.css`
- Modify: `frontend/styles/pages/variants.css`
- Modify: `frontend/styles/pages/variant-editor.css`
- Modify: `tests-e2e/reference.spec.js`
- Modify: `tests-e2e/account-workflows.spec.js`
- Modify: `tests-e2e/variants-catalog.spec.js`
- Modify: `tests-e2e/student-teacher.spec.js`

**Interfaces:**
- Consumes: завершённые компоненты Tasks 1–4.
- Produces: полностью проверенная единая система без металлических интерактивных поверхностей и без overflow на 390 px.

- [ ] **Step 1: Добавить финальный behavioral audit в Playwright**

В `tests-e2e/reference.spec.js` добавить тест representative controls без чтения исходного CSS:

```js
test("interactive controls stay flat and fit a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator('[data-start="exam"]')).toHaveCSS("background-image", "none");
  await page.locator("#authButton").click();
  await expect(page.locator("#authSubmitBtn")).toHaveCSS("background-image", "none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();

  await page.goto("/reference.html");
  await expect(page.locator(".reference-tab.active")).toHaveCSS("background-image", "none");
  await expect(page.locator(".copy-phrase").first()).toHaveCSS("min-height", "44px");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();

  await page.goto("/variants.html");
  await expect(page.locator(".year-filter.active")).toHaveCSS("background-image", "none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
```

- [ ] **Step 2: Запустить новый audit test**

Run:

```bash
npx playwright test tests-e2e/reference.spec.js -g "interactive controls stay flat"
```

Expected: PASS. Если тест падает, исправлять конкретный computed style или overflow в соответствующем page stylesheet, не ослаблять ожидание.

- [ ] **Step 3: Проверить остаточные металлические интерактивные правила**

Run:

```bash
rg -n "gold-metal|gold-emboss" frontend/styles
```

Expected: совпадения относятся только к декоративным линиям, точкам, неинтерактивным badges/status surfaces или устаревшим token definitions. Любое совпадение в селекторе button/link/tab/filter/action заменить flat action tokens и повторить целевой Playwright-тест этого экрана.

- [ ] **Step 4: Запустить обязательную проверку репозитория**

Run:

```bash
make check
```

Expected: YAML, Ruff, Ruff format, ESLint, JSON/content validation, repository hygiene, JS unit, Python unit и integration tests PASS; разрешены только документированные PostgreSQL skips без `TEST_DATABASE_URL`.

- [ ] **Step 5: Запустить полный браузерный набор**

Run:

```bash
make test-e2e
```

Expected: все Playwright tests PASS, включая новые palette/layout проверки.

- [ ] **Step 6: Выполнить визуальную проверку работающего сайта**

На `http://127.0.0.1:8080/` проверить desktop и 390 px для:

1. главной и hover кнопки запуска;
2. задания и результатов;
3. входа, личного кабинета и истории;
4. кабинета преподавателя с фильтрами и заявкой;
5. каталога и справочника;
6. редактора материалов.

Проверить, что кремовые controls читаются на белых и бордовых карточках, активные состояния бордовые, опасные действия красные, focus-visible не обрезается, а тексты и аудиоплееры не выходят за карточки.

- [ ] **Step 7: Закоммитить финальную приёмку**

```bash
git add frontend/styles frontend/pages frontend/js/account/account-view.js tests-e2e tests-js/unit/views.test.js
git commit -m "test: verify unified interface design system"
```
