import { personalRecordingStreamUrl } from "../shared/api.js";
import { escapeHtml, formatHistoryDate } from "../shared/progress.js";
import { pluralize } from "../shared/plural.js";

const safeNumericId = value => Number.isInteger(Number(value)) && Number(value) > 0;
const safeReviewAudioUrl = value => /^\/api\/review-recordings\/\d+$/.test(String(value || ""));

function reviewStatus(request) {
  if (request.status === "reviewed") return `Разобрано: ${request.total}/${request.maximum}`;
  if (request.status === "uploading") return "Загрузка не завершена";
  return "На разборе";
}

function runKind(entry) {
  if (entry.run?.mode === "exam") return "Полный экзамен";
  if (entry.tasks.length === 1) return `Задание ${entry.tasks[0]}`;
  return `Задания ${entry.tasks.join(", ")}`;
}

function runStatus(entry) {
  if (entry.recovered) return "Восстановлено из архива";
  return entry.run?.status === "completed" ? "Завершено" : "Прервано";
}

function entryDate(entry) {
  if (entry.run) return entry.run.completedAt || entry.run.startedAt;
  return entry.sortAt;
}

function historySummaryMarkup(entry) {
  const latestReview = entry.latestReview
    ? `<span class="history-review-status">${escapeHtml(reviewStatus(entry.latestReview))}</span>`
    : "";
  return `<span class="history-summary-main"><b>${escapeHtml(entry.variantLabel || entry.variantId || "Материал")}</b><span>${escapeHtml(runKind(entry))} · ${escapeHtml(runStatus(entry))}</span></span><span class="history-summary-meta"><time>${escapeHtml(formatHistoryDate(entryDate(entry)))}</time><span>${escapeHtml(pluralize(entry.recordings.length, "аудиозапись", "аудиозаписи", "аудиозаписей"))}</span>${latestReview}</span>`;
}

function recordingPosition(recording) {
  return recording.taskNumber === 1 && recording.questionNumber
    ? `Задание 1, вопрос ${recording.questionNumber}`
    : `Задание ${recording.taskNumber}`;
}

function personalRecordingsMarkup(recordings) {
  if (!recordings.length) return '<p class="history-empty-part">Аудиозаписей для этой попытки нет.</p>';
  return recordings.map(recording => {
    const audio = safeNumericId(recording.id)
      ? `<audio controls preload="none" src="${personalRecordingStreamUrl(Number(recording.id))}"></audio>`
      : "";
    return `<article class="history-audio-item"><div><b>${escapeHtml(recording.label || "Аудиозапись")}</b><span>${escapeHtml(recordingPosition(recording))}</span><small>Удалится ${escapeHtml(formatHistoryDate(recording.expiresAt * 1000))}</small></div>${audio}</article>`;
  }).join("");
}

function reviewAudioMarkup(request) {
  const recordings = (request.items || []).flatMap(item => item.recordings || []);
  if (!recordings.length) return "";
  return `<div class="history-review-audio">${recordings.map(recording => {
    const audio = safeReviewAudioUrl(recording.url)
      ? `<audio controls preload="none" src="${escapeHtml(recording.url)}"></audio>`
      : "";
    return `<label><span>${escapeHtml(recording.label || "Запись для разбора")}</span>${audio}</label>`;
  }).join("")}</div>`;
}

function reviewRequestsMarkup(requests) {
  if (!requests.length) return '<p class="history-empty-part">Заявок на разбор для этой попытки нет.</p>';
  return requests.map(request => {
    const kind = request.kind === "attempt" ? "Вся попытка" : "Одно задание";
    const discard = request.status === "uploading" && safeNumericId(request.id)
      ? `<button class="text-btn" type="button" data-discard-review-request="${Number(request.id)}">Удалить незавершённую загрузку</button>`
      : "";
    return `<article class="history-review-item"><div><b>${kind}</b><span>Задания ${escapeHtml((request.tasks || []).join(", "))} · ${escapeHtml(reviewStatus(request))}</span><small>${escapeHtml(formatHistoryDate(request.submittedAt * 1000))}</small></div>${reviewAudioMarkup(request)}${discard}</article>`;
  }).join("");
}

export function historyTimelineMarkup(entries) {
  if (!entries.length) {
    return '<p class="history-empty">Здесь появятся завершённые и прерванные тренировки.</p>';
  }
  return entries.map(entry => `<details class="history-entry" data-history-key="${escapeHtml(entry.key)}"><summary class="history-entry-summary">${historySummaryMarkup(entry)}</summary><div class="history-entry-details"><section class="history-recordings"><h2>Аудиозаписи</h2>${personalRecordingsMarkup(entry.recordings)}</section><section class="history-reviews"><h2>Разбор преподавателя</h2>${reviewRequestsMarkup(entry.reviewRequests)}</section></div></details>`).join("");
}

export function historyPageStateMarkup({ kind, message }) {
  const copy = `<p>${escapeHtml(message || "")}</p>`;
  if (kind === "guest") {
    return `${copy}<a class="secondary-btn" href="index.html?account=1">Войти и синхронизировать</a>`;
  }
  if (kind === "teacher") {
    return `${copy}<a class="secondary-btn" href="index.html?account=1">Открыть кабинет преподавателя</a>`;
  }
  return copy;
}
