import { escapeHtml, formatHistoryDate } from "../shared/progress.js";
import { reviewFields } from "../runner/review.js";

export function studentReviewRequestsMarkup(requests) {
  if (!requests.length) return '<p class="student-groups-empty">Заявок на разбор пока нет.</p>';
  return requests.map(request => {
    const status = request.status === "reviewed" ? `Разобрано: ${request.total}/${request.maximum}` : "На разборе";
    const kind = request.kind === "attempt" ? "Вся попытка" : "Одно задание";
    return `<article class="review-request-card"><p class="eyebrow">${kind}</p><h3>${escapeHtml(request.variantId)}</h3><span>Задания ${request.tasks.join(", ")} · ${status}</span><small>${formatHistoryDate(request.submittedAt * 1000)}</small></article>`;
  }).join("");
}

export function teacherReviewRequestsMarkup(requests) {
  if (!requests.length) return '<p class="teacher-empty">Заявок по выбранному фильтру нет.</p>';
  return requests.map(request => {
    const scores = Object.fromEntries((request.items || []).map(item => [String(item.task), item.scores || {}]));
    const recordings = (request.items || []).flatMap(item => item.recordings || []);
    return `<article class="teacher-review-request-card"><header><div><p class="eyebrow">${escapeHtml(request.studentName)}</p><h3>${escapeHtml(request.studentEmail)}</h3><span>${request.kind === "attempt" ? "Вся попытка" : "Одно задание"} · задания ${request.tasks.join(", ")}</span><small>${formatHistoryDate(request.submittedAt * 1000)}</small></div><b>${request.status === "reviewed" ? `${request.total}/${request.maximum}` : "На разборе"}</b></header><div class="submission-audio">${recordings.length ? recordings.map(recording => `<label><span>${escapeHtml(recording.label)}</span><audio controls preload="none" src="${escapeHtml(recording.url)}"></audio></label>`).join("") : "<p>Аудиозаписи отсутствуют.</p>"}</div><button class="text-btn" type="button" data-student-review-history="${request.id}">История заявок</button><form class="review-form" data-review-request="${request.id}" data-review-tasks="${request.tasks.join(",")}">${reviewFields(request.tasks, scores)}<button class="primary-btn" type="submit">${request.status === "reviewed" ? "Обновить оценку" : "Сохранить оценку"}</button></form></article>`;
  }).join("");
}
