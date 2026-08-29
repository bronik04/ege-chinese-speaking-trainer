import { escapeHtml, formatHistoryDate } from "../shared/progress.js";
import { reviewFields } from "../runner/review.js";

export function studentReviewRequestsMarkup(requests) {
  if (!requests.length) return '<p class="student-groups-empty">Заявок на разбор пока нет.</p>';
  return requests.map(request => {
    const status = request.status === "reviewed"
      ? `Разобрано: ${request.total}/${request.maximum}`
      : request.status === "uploading" ? "Загрузка не завершена" : "На разборе";
    const kind = request.kind === "attempt" ? "Вся попытка" : "Одно задание";
    const discard = request.status === "uploading"
      ? `<button class="text-btn" type="button" data-discard-review-request="${request.id}">Удалить незавершённую загрузку</button>`
      : "";
    return `<article class="review-request-card"><p class="eyebrow">${kind}</p><h3>${escapeHtml(request.variantId)}</h3><span>Задания ${request.tasks.join(", ")} · ${status}</span><small>${formatHistoryDate(request.submittedAt * 1000)}</small>${discard}</article>`;
  }).join("");
}

export function teacherReviewRequestsMarkup(requests) {
  if (!requests.length) return '<p class="teacher-empty">Заявок по выбранному фильтру нет.</p>';
  return requests.map(request => {
    const scores = Object.fromEntries((request.items || []).map(item => [String(item.task), item.scores || {}]));
    const recordings = (request.items || []).flatMap(item => item.recordings || []);
    return `<article class="teacher-review-request-card"><header class="teacher-request-heading"><div><p class="eyebrow">${escapeHtml(request.studentName)}</p><h3>${escapeHtml(request.studentEmail)}</h3><span>${request.kind === "attempt" ? "Вся попытка" : "Одно задание"} · задания ${request.tasks.join(", ")}</span><small>${formatHistoryDate(request.submittedAt * 1000)}</small></div><b class="teacher-request-status">${request.status === "reviewed" ? `${request.total}/${request.maximum}` : "На разборе"}</b></header><div class="submission-audio">${recordings.length ? recordings.map(recording => `<label><span>${escapeHtml(recording.label)}</span><audio controls preload="none" src="${escapeHtml(recording.url)}"></audio></label>`).join("") : "<p>Аудиозаписи отсутствуют.</p>"}</div><button class="text-btn" type="button" data-student-review-history="${request.id}">История заявок</button><form class="review-form" data-review-request="${request.id}" data-review-tasks="${request.tasks.join(",")}">${reviewFields(request.tasks, scores)}<button class="primary-btn" type="submit">${request.status === "reviewed" ? "Обновить оценку" : "Сохранить оценку"}</button></form></article>`;
  }).join("");
}

const privateReviewImage = value => /^\/api\/review-assets\/\d+$/.test(String(value || ""));

function materialTaskMarkup(task, material) {
  const list = (items, label) => Array.isArray(items) && items.length
    ? `<div><b>${label}</b><ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`
    : "";
  const images = [material.image, ...(Array.isArray(material.images) ? material.images : [])]
    .filter(privateReviewImage);
  const labels = Array.isArray(material.imageLabels) ? material.imageLabels : [];
  return `<section class="review-material-task"><p class="eyebrow">Материал задания ${task}</p><h4>${escapeHtml(material.title)}</h4>${material.situation ? `<p>${escapeHtml(material.situation)}</p>` : ""}${material.lead ? `<p>${escapeHtml(material.lead)}</p>` : ""}${material.banner ? `<p class="chinese-banner" lang="zh">${escapeHtml(material.banner)}</p>` : ""}${list(material.questions, "Что спросить")}${list(material.prompts, "План ответа")}${material.starter ? `<p class="starter" lang="zh">${escapeHtml(material.starter)}</p>` : ""}${images.length ? `<div class="review-material-images">${images.map((image, index) => `<figure><img src="${escapeHtml(image)}" alt="${escapeHtml(labels[index] || material.imageAlt || `Изображение ${index + 1}`)}">${labels[index] ? `<figcaption>${escapeHtml(labels[index])}</figcaption>` : ""}</figure>`).join("")}</div>` : ""}</section>`;
}

export function teacherReviewRequestDetailMarkup(request, history) {
  const material = request?.material && typeof request.material === "object" ? request.material : {};
  const tasks = Object.keys(material).sort((left, right) => Number(left) - Number(right));
  const materialMarkup = tasks.length
    ? tasks.map(task => materialTaskMarkup(task, material[task] || {})).join("")
    : "<p>Снимок материала недоступен.</p>";
  const historyMarkup = history.length
    ? history.map(item => `${escapeHtml(formatHistoryDate(item.submittedAt * 1000))}: ${item.status === "reviewed" ? `${item.total}/${item.maximum}` : "на разборе"}`).join(" · ")
    : "Других заявок ученика пока нет.";
  return `<div class="review-material-snapshot">${materialMarkup}</div><div class="attempt-history">${historyMarkup}</div>`;
}
