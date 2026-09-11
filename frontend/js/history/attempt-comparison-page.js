import { escapeHtml } from "../shared/progress.js";
import {
  AttemptComparisonError,
  buildAttemptComparison,
} from "./attempt-comparison.js";
import {
  attemptComparisonMarkup,
  comparisonPageStateMarkup,
} from "./attempt-comparison-view.js";
import { createHistoryPageController } from "./history-controller.js";
import { buildHistoryTimeline } from "./history-model.js";
import "../shared/site-shell.js";

const comparisonTitle = document.getElementById("comparisonTitle");
const comparisonStatus = document.getElementById("comparisonStatus");
const comparisonSourceErrors = document.getElementById("comparisonSourceErrors");
const comparisonContent = document.getElementById("comparisonContent");

const params = new URLSearchParams(window.location.search);
const leftRunId = params.get("left");
const rightRunId = params.get("right");
const validRunId = value => typeof value === "string" && value.length >= 1 && value.length <= 120;
const validSelection = validRunId(leftRunId) && validRunId(rightRunId);
const sourceLabels = {
  progress: "Прогресс",
  recordings: "Аудиозаписи",
  reviews: "Разборы преподавателя",
};

let controller = null;
let titleFocused = false;

function focusTitle() {
  if (titleFocused) return;
  comparisonTitle.focus({ preventScroll: true });
  titleFocused = true;
}

function renderSourceErrors(state) {
  const failures = Object.entries(sourceLabels).filter(([source]) => state.sourceErrors[source]);
  comparisonSourceErrors.classList.toggle("hidden", !failures.length);
  comparisonSourceErrors.innerHTML = failures.map(([source, label]) => (
    `<div class="comparison-source-error"><span><b>${label}:</b> ${escapeHtml(state.sourceErrors[source])}</span><button class="secondary-btn" type="button" data-retry-source="${source}"${state.sourceLoading[source] ? " disabled" : ""}>${state.sourceLoading[source] ? "Повторяем…" : "Повторить"}</button></div>`
  )).join("");
}

function renderPageState(kind, status, message = "") {
  comparisonStatus.textContent = status;
  comparisonContent.innerHTML = comparisonPageStateMarkup({ kind, message });
}

function renderComparison(state) {
  if (state.mode !== "student") {
    comparisonSourceErrors.classList.add("hidden");
    comparisonSourceErrors.innerHTML = "";
    renderPageState(state.mode, "Сравнение недоступно", state.sourceErrors.auth || "");
    focusTitle();
    return;
  }
  renderSourceErrors(state);
  if (state.sourceLoading.progress) {
    renderPageState("loading", "Загружаем попытки…");
    return;
  }
  const entries = buildHistoryTimeline({
    runs: state.progress.runs,
    recordings: state.recordings,
    reviewRequests: state.reviewRequests,
  });
  let comparison;
  try {
    comparison = buildAttemptComparison(entries, leftRunId, rightRunId);
  } catch (error) {
    const kind = error instanceof AttemptComparisonError ? error.code : "network";
    renderPageState(kind, "Сравнение недоступно");
    focusTitle();
    return;
  }
  comparisonContent.innerHTML = attemptComparisonMarkup(comparison);
  const loading = Object.values(state.sourceLoading).some(Boolean);
  const failed = Object.values(state.sourceErrors).some(Boolean);
  comparisonStatus.textContent = loading
    ? "Обновляем данные сравнения…"
    : failed ? "Сравнение загружено частично" : "Сравнение загружено";
  if (!loading) focusTitle();
}

comparisonSourceErrors.addEventListener("click", event => {
  const button = event.target.closest("[data-retry-source]");
  if (button && controller) controller.retry(button.dataset.retrySource);
});

if (!validSelection) {
  renderPageState("invalid_url", "Сравнение недоступно");
  focusTitle();
} else {
  controller = createHistoryPageController({ render: renderComparison });
  controller.load();
}
