import { escapeHtml } from "../shared/progress.js";
import { pluralize } from "../shared/plural.js";
import { buildComparisonSelection } from "./attempt-comparison.js";
import { createHistoryPageController } from "./history-controller.js";
import { buildHistoryTimeline } from "./history-model.js";
import { historyPageStateMarkup, historyTimelineMarkup } from "./history-view.js";
import "../shared/site-shell.js";

const historyCount = document.getElementById("historyCount");
const historyStatus = document.getElementById("historyStatus");
const historyNotice = document.getElementById("historyNotice");
const historySourceErrors = document.getElementById("historySourceErrors");
const historyTimeline = document.getElementById("historyTimeline");
const historyCompareBar = document.getElementById("historyCompareBar");
const historyCompareStatus = document.getElementById("historyCompareStatus");
const historyCompareBtn = document.getElementById("historyCompareBtn");

let latestState = null;
let selectedRunIds = [];

const sourceLabels = {
  progress: "Прогресс",
  recordings: "Аудиозаписи",
  reviews: "Разборы преподавателя",
};

function renderErrors(sourceErrors) {
  const failures = Object.entries(sourceLabels).filter(([source]) => sourceErrors[source]);
  historySourceErrors.classList.toggle("hidden", !failures.length);
  historySourceErrors.innerHTML = failures.map(([source, label]) => (
    `<div class="history-source-error"><span><b>${label}:</b> ${escapeHtml(sourceErrors[source])}</span><button class="secondary-btn history-retry" type="button" data-retry-source="${source}">Повторить</button></div>`
  )).join("");
}

function renderNotice(state) {
  if (state.mode === "student") {
    historyNotice.classList.add("hidden");
    historyNotice.innerHTML = "";
    return;
  }
  const message = state.mode === "teacher"
    ? "История учеников и очередь разборов находятся в кабинете преподавателя."
    : state.sourceErrors.auth
      ? "Не удалось проверить вход. Показана история из этого браузера."
      : "Сейчас показана история из этого браузера. Войдите, чтобы синхронизировать попытки и видеть сохранённые аудиозаписи.";
  historyNotice.innerHTML = historyPageStateMarkup({ kind: state.mode, message });
  historyNotice.classList.remove("hidden");
}

function renderHistory(state) {
  latestState = state;
  const entries = state.mode === "teacher" ? [] : buildHistoryTimeline({
    runs: state.progress.runs,
    recordings: state.recordings,
    reviewRequests: state.reviewRequests,
  });
  historyCount.textContent = state.mode === "teacher"
    ? "История учеников"
    : pluralize(entries.length, "попытка", "попытки", "попыток");
  historyStatus.textContent = state.mode === "teacher"
    ? "Аккаунт преподавателя"
    : state.mode === "guest"
      ? "Локальная история загружена"
      : Object.values(state.sourceErrors).some(Boolean)
        ? "История загружена частично"
        : `Синхронизировано · ${state.user.email}`;
  if (state.mode === "student") {
    const comparison = buildComparisonSelection(entries, selectedRunIds);
    selectedRunIds = comparison.selectedIds;
    historyTimeline.innerHTML = historyTimelineMarkup(entries, { comparison });
    historyCompareStatus.textContent = comparison.selectedIds.length
      ? `Выбрано ${comparison.selectedIds.length} из 2`
      : "Выберите две завершённые попытки";
    historyCompareBtn.disabled = !comparison.canCompare;
    historyCompareBar.classList.remove("hidden");
  } else {
    selectedRunIds = [];
    historyTimeline.innerHTML = state.mode === "teacher" ? "" : historyTimelineMarkup(entries);
    historyCompareBtn.disabled = true;
    historyCompareBar.classList.add("hidden");
  }
  renderNotice(state);
  renderErrors(state.sourceErrors);
}

const controller = createHistoryPageController({ render: renderHistory });

historySourceErrors.addEventListener("click", event => {
  const button = event.target.closest("[data-retry-source]");
  if (button) controller.retry(button.dataset.retrySource);
});

historyTimeline.addEventListener("click", async event => {
  const compareButton = event.target.closest("[data-compare-run]");
  if (compareButton && latestState?.mode === "student") {
    const runId = compareButton.dataset.compareRun;
    selectedRunIds = selectedRunIds.includes(runId)
      ? selectedRunIds.filter(id => id !== runId)
      : [...selectedRunIds, runId].slice(0, 2);
    renderHistory(latestState);
    return;
  }
  const button = event.target.closest("[data-discard-review-request]");
  if (!button) return;
  button.disabled = true;
  await controller.discardReviewRequest(Number(button.dataset.discardReviewRequest));
});

historyCompareBtn.addEventListener("click", () => {
  if (selectedRunIds.length !== 2) return;
  const query = new URLSearchParams({ left: selectedRunIds[0], right: selectedRunIds[1] });
  window.location.assign(`compare.html?${query}`);
});

controller.load();
