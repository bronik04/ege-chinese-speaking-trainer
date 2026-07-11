import { escapeHtml } from "./progress.js";
import "./site-shell.js";

const $ = id => document.getElementById(id);
let library = null;
let activeTask = window.location.hash.replace("#", "") || "task-1";

function normalize(value) {
  return String(value || "").toLocaleLowerCase("ru").replaceAll("ё", "е");
}

function matchesQuery(value, query) {
  const haystack = normalize(value);
  return query.split(/\s+/).every(token => {
    const forms = [token];
    if (/^[а-я]{5,}[аяыиую]$/u.test(token)) forms.push(token.slice(0, -1));
    return forms.some(form => haystack.includes(form));
  });
}

function taskMatches(task, query) {
  if (!query) return true;
  return matchesQuery(JSON.stringify(task), query);
}

function filteredTask(task, query) {
  if (!query) return task;
  const groups = task.groups.map(group => ({
    ...group,
    items: group.items.filter(item => matchesQuery(`${item.ru} ${item.zh} ${item.note || ""}`, query)),
  })).filter(group => group.items.length || matchesQuery(`${group.title} ${group.description || ""}`, query));
  const examples = task.examples.filter(example => matchesQuery(JSON.stringify(example), query));
  return { ...task, groups, examples };
}

function tabsMarkup(tasks) {
  return tasks.map(task => `<button class="reference-tab${task.id === activeTask ? " active" : ""}" type="button" data-reference-task="${escapeHtml(task.id)}"><b>${escapeHtml(task.number)}</b><span>${escapeHtml(task.title)}</span></button>`).join("");
}

function groupMarkup(group, open) {
  const items = group.items.map(item => `<article class="phrase-card"><b lang="zh">${escapeHtml(item.zh)}</b><span>${escapeHtml(item.ru)}</span><button class="copy-phrase" type="button" data-copy-phrase="${escapeHtml(item.zh)}" aria-label="Скопировать фразу">⧉</button></article>`).join("");
  return `<details class="reference-group"${open ? " open" : ""}><summary>${escapeHtml(group.title)}</summary>${group.description ? `<p class="reference-group-description">${escapeHtml(group.description)}</p>` : ""}<div class="phrase-list">${items}</div></details>`;
}

function exampleMarkup(example) {
  return `<article class="example-card"><h4>${escapeHtml(example.title)}</h4><p class="example-context">${escapeHtml(example.context)}</p><div class="example-text" lang="zh">${example.paragraphs.map(paragraph => `<p>${escapeHtml(paragraph)}</p>`).join("")}</div><ul class="example-criteria">${example.criteria.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul></article>`;
}

function criteriaMarkup(criteria = []) {
  if (!criteria.length) return "";
  const maximum = criteria.reduce((sum, criterion) => sum + Number(criterion.maximum || 0), 0);
  const scoreLabel = value => {
    const number = Number(value);
    if (number % 10 === 1 && number % 100 !== 11) return "балл";
    if ([2, 3, 4].includes(number % 10) && ![12, 13, 14].includes(number % 100)) return "балла";
    return "баллов";
  };
  const cards = criteria.map(criterion => {
    const details = criterion.details?.length ? `<ul>${criterion.details.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "";
    return `<article class="criteria-card"><div><h4>${escapeHtml(criterion.title)}</h4><b>${escapeHtml(criterion.maximum)} ${scoreLabel(criterion.maximum)}</b></div><p>${escapeHtml(criterion.description)}</p>${details}</article>`;
  }).join("");
  return `<section class="reference-criteria" aria-labelledby="criteriaTitle"><header><div><p class="eyebrow">Самопроверка</p><h3 id="criteriaTitle">Критерии оценивания</h3></div><strong>Максимум ${maximum}</strong></header><p class="criteria-note">Если за решение коммуникативной задачи в заданиях 2 или 3 выставлено 0 баллов, остальные критерии также оцениваются в 0 баллов.</p><div class="criteria-grid">${cards}</div></section>`;
}

function taskMarkup(task, query) {
  const groups = task.groups.map((group, index) => groupMarkup(group, Boolean(query) || index === 0)).join("");
  const examples = task.examples.length ? `<div class="examples-heading"><p class="eyebrow">Разбор образца</p><h3>Примеры ответов</h3></div><div class="example-list">${task.examples.map(exampleMarkup).join("")}</div>` : "";
  if (!task.groups.length && !task.examples.length) return '<p class="reference-empty">По этому запросу ничего не найдено. Попробуйте другую формулировку.</p>';
  return `<header class="reference-task-head"><div><p class="eyebrow">Задание ${escapeHtml(task.number)}</p><h2>${escapeHtml(task.title)}</h2><p>${escapeHtml(task.subtitle)}</p></div><span class="reference-timing">${escapeHtml(task.timing)}</span></header><ul class="reference-tips">${task.tips.map(tip => `<li>${escapeHtml(tip)}</li>`).join("")}</ul>${criteriaMarkup(task.criteria)}<div class="reference-groups">${groups}</div>${examples}`;
}

function render() {
  const query = normalize($("referenceSearch").value.trim());
  const available = library.tasks.filter(task => taskMatches(task, query));
  if (!available.some(task => task.id === activeTask)) activeTask = available[0]?.id || library.tasks[0].id;
  $("referenceTabs").innerHTML = tabsMarkup(library.tasks);
  document.querySelectorAll("[data-reference-task]").forEach(button => {
    button.hidden = Boolean(query) && !available.some(task => task.id === button.dataset.referenceTask);
  });
  const task = library.tasks.find(item => item.id === activeTask);
  const filtered = filteredTask(task, query);
  $("referenceContent").innerHTML = taskMarkup(filtered, query);
  const visibleCount = filtered.groups.reduce((sum, group) => sum + group.items.length, 0);
  $("referenceStatus").textContent = query ? `Найдено фраз: ${visibleCount} · примеров: ${filtered.examples.length}` : `${task.groups.length} разделов · ${visibleCount} фраз · ${task.examples.length} примеров`;
}

function toast(message) {
  $("referenceToast").textContent = message;
  $("referenceToast").classList.remove("hidden");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => $("referenceToast").classList.add("hidden"), 1700);
}

$("referenceTabs").addEventListener("click", event => {
  const button = event.target.closest("[data-reference-task]");
  if (!button) return;
  activeTask = button.dataset.referenceTask;
  window.history.replaceState({}, "", `#${activeTask}`);
  render();
});
$("referenceSearch").addEventListener("input", render);
$("referenceContent").addEventListener("click", async event => {
  const button = event.target.closest("[data-copy-phrase]");
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.copyPhrase);
    toast("Фраза скопирована");
  } catch (_) {
    toast("Не удалось скопировать фразу");
  }
});

async function initialize() {
  try {
    const response = await fetch("/data/reference/library.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    library = await response.json();
    if (!library.tasks.some(task => task.id === activeTask)) activeTask = "task-1";
    render();
  } catch (error) {
    $("referenceStatus").textContent = "Не удалось загрузить справочник";
    $("referenceContent").innerHTML = '<p class="reference-empty">Обновите страницу или проверьте подключение к серверу.</p>';
    console.error("Reference library loading failed", error);
  }
}

initialize();
