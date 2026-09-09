import { api } from "../shared/api.js";
import { loadLocalProgress, progressStorageKeys } from "../shared/progress.js";
import { pluralize } from "../shared/plural.js";
import { buildHistoryTimeline } from "./history-model.js";
import { historyPageStateMarkup, historyTimelineMarkup } from "./history-view.js";
import "../shared/site-shell.js";

const historyCount = document.getElementById("historyCount");
const historyStatus = document.getElementById("historyStatus");
const historyNotice = document.getElementById("historyNotice");
const historyTimeline = document.getElementById("historyTimeline");

function renderTimeline(progress) {
  const entries = buildHistoryTimeline({ runs: progress.runs, recordings: [], reviewRequests: [] });
  historyCount.textContent = pluralize(entries.length, "попытка", "попытки", "попыток");
  historyTimeline.innerHTML = historyTimelineMarkup(entries);
}

function showNotice(kind, message) {
  historyNotice.innerHTML = historyPageStateMarkup({ kind, message });
  historyNotice.classList.remove("hidden");
}

function loadLocal(userId = null) {
  return loadLocalProgress(progressStorageKeys(userId), {
    onError: message => { historyStatus.textContent = message; },
  });
}

function renderGuest({ authUnavailable = false } = {}) {
  renderTimeline(loadLocal());
  showNotice(
    "guest",
    authUnavailable
      ? "Не удалось проверить вход. Показана история из этого браузера."
      : "Сейчас показана история из этого браузера. Войдите, чтобы синхронизировать попытки и видеть сохранённые аудиозаписи.",
  );
  historyStatus.textContent = "Локальная история загружена";
}

async function initialize() {
  let user;
  try {
    user = (await api("/api/auth/me")).user;
  } catch (error) {
    renderGuest({ authUnavailable: error.status !== 401 });
    return;
  }
  if (user.role === "teacher") {
    historyCount.textContent = "История учеников";
    historyTimeline.innerHTML = "";
    showNotice("teacher", "История учеников и очередь разборов находятся в кабинете преподавателя.");
    historyStatus.textContent = "Аккаунт преподавателя";
    return;
  }
  renderTimeline(loadLocal(user.id));
  historyStatus.textContent = `Локальная история · ${user.email}`;
}

initialize();
