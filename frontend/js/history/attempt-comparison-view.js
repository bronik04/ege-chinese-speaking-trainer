import { personalRecordingStreamUrl } from "../shared/api.js";
import { escapeHtml, formatHistoryDate } from "../shared/progress.js";
import { pluralize } from "../shared/plural.js";
import { REVIEW_CRITERIA } from "../runner/review.js";

const safeNumericId = value => Number.isInteger(Number(value)) && Number(value) > 0;
const safeReviewAudioUrl = value => /^\/api\/review-recordings\/[1-9]\d*$/.test(String(value || ""));

function attemptKind(attempt) {
  return attempt.tasks.length === 3 ? "Полный экзамен" : `Задание ${attempt.tasks.join(", ")}`;
}

function attemptHeaderMarkup(attempt, label) {
  return `<article class="comparison-attempt"><p class="eyebrow">${label}</p><h2>${escapeHtml(attempt.variantLabel || attempt.variantId || "Материал")}</h2><p>${escapeHtml(attemptKind(attempt))}</p><time>${escapeHtml(formatHistoryDate(attempt.completedAt))}</time></article>`;
}

function criterionLabel(taskNumber, key) {
  return REVIEW_CRITERIA[taskNumber]?.find(item => item.key === key)?.label || key;
}

function scoreMarkup(score, taskNumber) {
  if (!score) return '<p class="comparison-empty">Оценки пока нет</p>';
  const knownOrder = new Map((REVIEW_CRITERIA[taskNumber] || []).map((item, index) => [item.key, index]));
  const criteria = Object.entries(score.criteria || {}).sort(([left], [right]) => (
    (knownOrder.get(left) ?? Number.MAX_SAFE_INTEGER) - (knownOrder.get(right) ?? Number.MAX_SAFE_INTEGER)
    || left.localeCompare(right)
  ));
  const list = criteria.length
    ? `<dl class="comparison-criteria">${criteria.map(([key, value]) => `<div><dt>${escapeHtml(criterionLabel(taskNumber, key))}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>`
    : "";
  return `<div class="comparison-score"><strong>${escapeHtml(score.total)}/${escapeHtml(score.maximum)}</strong>${list}</div>`;
}

function deltaMarkup(delta) {
  if (delta === null) return '<span class="comparison-delta is-unavailable">Изменение недоступно</span>';
  if (delta === 0) return '<span class="comparison-delta is-neutral">0 баллов · без изменений</span>';
  const absolute = Math.abs(delta);
  const value = `${delta > 0 ? "+" : "−"}${pluralize(absolute, "балл", "балла", "баллов")}`;
  return `<span class="comparison-delta ${delta > 0 ? "is-positive" : "is-negative"}">${value}</span>`;
}

function audioUrl(slot) {
  if (slot?.source === "personal" && safeNumericId(slot.recording?.id)) {
    return personalRecordingStreamUrl(Number(slot.recording.id));
  }
  if (slot?.source === "review" && safeReviewAudioUrl(slot.recording?.url)) {
    return slot.recording.url;
  }
  return null;
}

function audioMarkup(slot) {
  const url = audioUrl(slot);
  if (!url) return '<p class="comparison-empty">Запись недоступна</p>';
  const label = slot.recording?.label || slot.label || "Аудиозапись";
  return `<label class="comparison-audio"><span>${escapeHtml(label)}</span><audio preload="none" controls src="${escapeHtml(url)}"></audio></label>`;
}

function recordingRowsMarkup(left, right) {
  const rightByKey = new Map(right.map(slot => [slot.key, slot]));
  const keys = [...new Set([...left.map(slot => slot.key), ...right.map(slot => slot.key)])];
  return keys.map(key => {
    const leftSlot = left.find(slot => slot.key === key);
    const rightSlot = rightByKey.get(key);
    const label = leftSlot?.label || rightSlot?.label || "Ответ";
    return `<section class="comparison-recording-row"><h3>${escapeHtml(label)}</h3><div class="comparison-side" data-comparison-side="left"><span class="comparison-side-label">Первая попытка</span>${audioMarkup(leftSlot)}</div><div class="comparison-side" data-comparison-side="right"><span class="comparison-side-label">Вторая попытка</span>${audioMarkup(rightSlot)}</div></section>`;
  }).join("");
}

function taskMarkup(task) {
  return `<article class="comparison-task" aria-labelledby="comparison-task-${task.number}"><header><div><p class="eyebrow">Сопоставление результата</p><h2 id="comparison-task-${task.number}">Задание ${task.number}</h2></div>${deltaMarkup(task.delta)}</header><div class="comparison-score-grid"><section class="comparison-side" data-comparison-side="left"><h3>Первая попытка</h3>${scoreMarkup(task.left.score, task.number)}</section><section class="comparison-side" data-comparison-side="right"><h3>Вторая попытка</h3>${scoreMarkup(task.right.score, task.number)}</section></div><div class="comparison-recordings"><h3>Аудиозаписи</h3>${recordingRowsMarkup(task.left.recordings, task.right.recordings)}</div></article>`;
}

export function attemptComparisonMarkup(comparison) {
  return `<section class="comparison-attempts">${attemptHeaderMarkup(comparison.left, "Первая попытка")}${attemptHeaderMarkup(comparison.right, "Вторая попытка")}</section><section class="comparison-tasks">${comparison.tasks.map(taskMarkup).join("")}</section>`;
}

const stateMessages = {
  loading: "Загружаем сравнение…",
  guest: "Войдите как ученик, чтобы сравнить свои попытки.",
  teacher: "Сравнение попыток доступно только ученику.",
  invalid_url: "Выберите две попытки в истории и откройте сравнение снова.",
  attempt_missing: "Одна из выбранных попыток не найдена в вашей истории.",
  attempt_ineligible: "Для сравнения подходят только завершённые попытки.",
  attempt_incompatible: "У выбранных попыток разные наборы заданий.",
  network: "Не удалось загрузить сравнение.",
};

export function comparisonPageStateMarkup({ kind, message = "" }) {
  const details = message ? `<small>${escapeHtml(message)}</small>` : "";
  return `<div class="comparison-page-state" data-comparison-state="${escapeHtml(kind)}"><p>${escapeHtml(stateMessages[kind] || stateMessages.network)}</p>${details}</div>`;
}
