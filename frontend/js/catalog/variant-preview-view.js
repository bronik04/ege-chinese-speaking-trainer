import { isSafeMaterialImageUrl } from "./variant-preview.js";
import { pluralize } from "../shared/plural.js";
import { escapeHtml } from "../shared/progress.js";

const STATE_MESSAGES = Object.freeze({
  loading: "Загружаем предпросмотр…",
  not_found: "Вариант не найден. Возможно, он удалён или недоступен.",
  forbidden: "Чтобы открыть этот вариант, нужно войти в аккаунт.",
  network: "Не удалось загрузить предпросмотр. Проверьте подключение и попробуйте ещё раз.",
  invalid_material: "Предпросмотр этого варианта не удалось подготовить.",
  invalid_request: "В ссылке не указан вариант для предпросмотра.",
});

function imageMarkup(image) {
  if (!image || !isSafeMaterialImageUrl(image.src)) {
    return '<div class="variant-preview-image-missing" role="img" aria-label="Изображение недоступно"><span>Изображение недоступно</span></div>';
  }
  const alt = typeof image.alt === "string" ? image.alt : "";
  const label = typeof image.label === "string" && image.label.trim() ? image.label : null;
  return `<img src="${escapeHtml(image.src)}" alt="${escapeHtml(alt)}" loading="lazy">${label ? `<figcaption>${escapeHtml(label)}</figcaption>` : ""}`;
}

function taskMarkup(task, index) {
  const headingId = `variant-preview-task-${index + 1}`;
  const images = Array.isArray(task?.images) ? task.images : [];
  return `<section class="variant-preview-task" aria-labelledby="${headingId}">
    <header class="variant-preview-task-heading"><span aria-hidden="true">${String(task?.number || index + 1).padStart(2, "0")}</span><h2 id="${headingId}">${escapeHtml(task?.title || "Задание")}</h2></header>
    <div class="variant-preview-gallery" data-images="${images.length}">${images.map(image => `<figure>${imageMarkup(image)}</figure>`).join("")}</div>
  </section>`;
}

export function variantPreviewMarkup(preview) {
  const tasks = Array.isArray(preview?.tasks) ? preview.tasks : [];
  const kind = preview?.kind === "task" ? `Отдельное задание ${preview.taskNumber}` : "Полный вариант";
  const query = new URLSearchParams({ variant: String(preview?.id || "") });
  return `<section class="variant-preview-summary" aria-label="О варианте">
    <div class="variant-preview-summary-copy">
      <p class="variant-preview-kind">${escapeHtml(kind)}</p>
      <h2>${escapeHtml(preview?.label || "Вариант")}</h2>
      <p class="variant-preview-source">${escapeHtml(preview?.source || "")}</p>
      <dl class="variant-preview-facts">
        <div><dt>Год</dt><dd>${escapeHtml(preview?.year ?? "—")}</dd></div>
        <div><dt>Время</dt><dd>≈ ${escapeHtml(pluralize(preview?.totalMinutes, "минута", "минуты", "минут"))}</dd></div>
      </dl>
    </div>
    <a class="variant-preview-start" href="index.html?${escapeHtml(query.toString())}">Перейти к тренировке →</a>
  </section>
  <div class="variant-preview-tasks">${tasks.map(taskMarkup).join("")}</div>`;
}

export function variantPreviewStateMarkup({ kind, message } = {}) {
  const state = Object.hasOwn(STATE_MESSAGES, kind) ? kind : "network";
  const text = typeof message === "string" && message ? message : STATE_MESSAGES[state];
  const loading = state === "loading";
  const canRetry = !loading && state !== "invalid_request";
  return `<div class="variant-preview-state variant-preview-state-${state}" role="${loading ? "status" : "alert"}">
    <p>${escapeHtml(text)}</p>
    ${canRetry ? '<button type="button" data-preview-retry>Попробовать снова</button>' : ""}
  </div>`;
}
