import { createRunnerController } from "./runner-controller.js";
import {
  PROGRESS_ACCOUNT_PREFIX, PROGRESS_GUEST_KEY, defaultProgress,
  escapeHtml, formatHistoryDate, loadLocalProgress,
} from "../shared/progress.js";
import { shortTime } from "./task-view.js";
import { plural, pluralize } from "../shared/plural.js";
import { createAccountController } from "../account/account-controller.js";
import { fullyRecordedTasks } from "../account/account-review-requests-controller.js";
import { enhanceProjectSelects } from "../shared/project-select.js";
import { enhanceMaterialList } from "../shared/material-list.js";
import "../shared/site-shell.js";

const $ = (id) => document.getElementById(id);

const screens = {
  home: $("homeScreen"),
  runner: $("runnerScreen"),
  result: $("resultScreen")
};

let variantIndex = [];
let variant = null;
const variantCache = new Map();
let progressStorageKey = PROGRESS_GUEST_KEY;
let progress = loadLocalProgress(progressStorageKey);
// Прогон, который лежал в хранилище на момент загрузки страницы. Прерванным
// считается только он: тренировка, начатая пользователем пока идёт авторизация,
// и активный прогон, подтянутый с сервера, сюда не попадают.
const interruptedRunId = progress.activeRun?.id ?? null;
let account = null;
let runner = null;
let reviewRequestSent = false;

const taskData = (task) => variant.tasks[String(task)];

function showScreen(name) {
  Object.entries(screens).forEach(([key, node]) => node.classList.toggle("hidden", key !== name));
  $("referenceLink").classList.toggle("hidden", name === "runner");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.add("hidden"), 3000);
}

function switchProgressScope(user, { adoptGuest = false } = {}) {
  const nextKey = user ? `${PROGRESS_ACCOUNT_PREFIX}${user.id}` : PROGRESS_GUEST_KEY;
  if (nextKey === progressStorageKey) return;
  const hasScopedProgress = localStorage.getItem(nextKey) !== null;
  if (user && adoptGuest && !hasScopedProgress && progressStorageKey === PROGRESS_GUEST_KEY) {
    const guestProgress = loadLocalProgress(PROGRESS_GUEST_KEY);
    const shouldTransfer = guestProgress.runs.length > 0 || Boolean(guestProgress.activeRun);
    progress = shouldTransfer ? guestProgress : defaultProgress();
    if (shouldTransfer) localStorage.removeItem(PROGRESS_GUEST_KEY);
  } else {
    progress = loadLocalProgress(nextKey);
  }
  progressStorageKey = nextKey;
  localStorage.setItem(progressStorageKey, JSON.stringify(progress));
}

function saveProgressLocal(sync = true) {
  progress.updatedAt = new Date().toISOString();
  progress.runs = progress.runs.slice(0, 100);
  localStorage.setItem(progressStorageKey, JSON.stringify(progress));
  renderProgress();
  if (sync && account?.user) account.scheduleProgressSync();
}

function renderProgress() {
  const completed = progress.runs.filter(run => run.status === "completed");
  const tasks = completed.reduce((sum, run) => sum + (run.completedTasks?.length || 0), 0);
  const latest = progress.runs[0];
  $("progressSummary").textContent = completed.length
    ? `${pluralize(completed.length, "тренировка", "тренировки", "тренировок")} · ${pluralize(tasks, "задание", "задания", "заданий")}`
    : "Тренировок пока нет";
  $("progressSyncStatus").textContent = account?.user
    ? `Синхронизировано · ${account.user.email}`
    : latest ? `Последняя: ${formatHistoryDate(latest.completedAt || latest.startedAt)}` : "Сохраняется в этом браузере";
  $("accountRuns").textContent = completed.length;
  $("accountRunsLabel").textContent = plural(completed.length, "завершённая тренировка", "завершённые тренировки", "завершённых тренировок");
  renderHistory();
}

function renderHistory() {
  if (!progress.runs.length) {
    $("historyList").innerHTML = '<p class="history-empty">Здесь появятся завершённые и прерванные тренировки.</p>';
    return;
  }
  $("historyList").innerHTML = progress.runs.map(run => {
    const status = run.status === "completed" ? "Завершено" : "Прервано";
    const taskText = run.mode === "exam" ? "Полный экзамен" : `Задание ${run.tasks?.[0] || ""}`;
    const variantName = escapeHtml(run.variantLabel || run.variantId || "Вариант");
    return `<article class="history-item"><div class="history-copy"><b>${variantName}</b><span>${escapeHtml(taskText)} · ${status}</span></div><time>${escapeHtml(formatHistoryDate(run.completedAt || run.startedAt))}</time></article>`;
  }).join("");
}

function markTaskCompleted(task) {
  if (!progress.activeRun) return;
  const completed = new Set(progress.activeRun.completedTasks || []);
  completed.add(task);
  progress.activeRun.completedTasks = [...completed];
  progress.activeRun.currentTask = task;
  saveProgressLocal();
}

function finalizeActiveRun(status, recordingsCount = 0) {
  if (!progress.activeRun) return;
  progress.runs.unshift({
    ...progress.activeRun,
    status,
    completedAt: new Date().toISOString(),
    recordingsCount
  });
  progress.activeRun = null;
  saveProgressLocal();
}

function recoverInterruptedRun() {
  if (!progress.activeRun || progress.activeRun.id !== interruptedRunId) return;
  progress.runs.unshift({ ...progress.activeRun, status: "interrupted", completedAt: new Date().toISOString(), recordingsCount: 0 });
  progress.activeRun = null;
  saveProgressLocal();
}

function clearHistory() {
  if (!confirm("Удалить историю тренировок из этого браузера? Сохранённые аудиозаписи в личном архиве не удалятся.")) return;
  progress.runs = [];
  progress.activeRun = null;
  saveProgressLocal();
  closeModal($("progressModal"));
  toast("Локальная история очищена; личный архив сохранён");
}

function setStartButtonsEnabled(enabled) {
  document.querySelectorAll("[data-start]").forEach(button => {
    const unavailableForTask = variant?.kind === "task" && button.dataset.start !== String(variant.taskNumber);
    button.disabled = !enabled || unavailableForTask;
  });
}

async function initVariants() {
  try {
    const response = await fetch("/api/materials");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    variantIndex = payload.materials;
    $("materialAccessNotice").classList.toggle("hidden", variantIndex.length !== 1);
    $("variantCount").textContent = variantIndex.length;
    $("variantCountLabel").textContent = plural(variantIndex.length, "вариант", "варианта", "вариантов");
    $("variantSelect").innerHTML = variantIndex.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}${item.kind === "task" ? ` · задание ${item.taskNumber}` : ""}</option>`).join("");
    const requestedVariant = new URLSearchParams(window.location.search).get("variant");
    const preferredVariant = variantIndex.some(item => item.id === requestedVariant)
      ? requestedVariant
      : variantIndex.some(item => item.id === progress.settings.lastVariant)
        ? progress.settings.lastVariant
        : variantIndex[0].id;
    $("variantSelect").value = preferredVariant;
    $("fastMode").checked = Boolean(progress.settings.fastMode);
    await loadVariant(preferredVariant);
  } catch (error) {
    $("variantSource").textContent = "Не удалось загрузить задания";
    toast("Запустите проект через локальный сервер");
    console.error("Variant loading failed", error);
  }
}

async function loadVariant(id, snapshot = null) {
  setStartButtonsEnabled(false);
  const item = variantIndex.find(entry => entry.id === id);
  if (!item && !snapshot) return;
  try {
    if (snapshot) variantCache.set(id, snapshot);
    if (!variantCache.has(id)) {
      const response = await fetch(`/api/materials/${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      variantCache.set(id, (await response.json()).material);
    }
    variant = variantCache.get(id);
    const url = new URL(window.location.href);
    url.searchParams.set("variant", id);
    window.history.replaceState({}, "", url);
    updateVariantUI();
    setStartButtonsEnabled(true);
  } catch (error) {
    toast("Не удалось загрузить выбранный вариант");
    console.error("Variant loading failed", error);
  }
}

function updateVariantUI() {
  $("variantSource").textContent = variant.source;
  $("totalMinutes").textContent = variant.totalMinutes;
  $("totalMinutesLabel").textContent = plural(variant.totalMinutes, "минута", "минуты", "минут");
  if (taskData(1)) $("task1Timing").textContent = `${shortTime(taskData(1).prepSeconds)} + 5 × ${shortTime(taskData(1).answerSeconds)}`;
  if (taskData(2)) $("task2Timing").textContent = `${shortTime(taskData(2).prepSeconds)} + до ${shortTime(taskData(2).answerSeconds)}`;
  if (taskData(3)) {
    $("task3Timing").textContent = `${shortTime(taskData(3).prepSeconds)} + до ${shortTime(taskData(3).answerSeconds)}`;
    $("task3CardTitle").firstChild.textContent = taskData(3).title.startsWith("Сравнение") ? "Сравнение фото" : "Проектная работа";
  }
}

function renderReviewRequestChooser() {
  const panel = $("reviewRequestPanel");
  const run = runner.getCompletedRun();
  const tasks = runner.getCompletedTasks();
  const recordings = runner.getCompletedRecordings();
  const recordedTasks = fullyRecordedTasks(tasks, recordings);
  const isStudent = account?.user?.role === "student";
  if (!run || !tasks.length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const taskSelect = $("reviewTaskSelect");
  taskSelect.innerHTML = recordedTasks.map(task => `<option value="${task}">Задание ${task}</option>`).join("");
  const taskChoice = document.querySelector('[name="reviewKind"][value="task"]');
  const attemptChoice = document.querySelector('[name="reviewKind"][value="attempt"]');
  const submit = $("sendReviewRequestBtn");
  const message = $("reviewRequestMessage");
  const update = () => {
    const isAttempt = attemptChoice.checked;
    taskSelect.disabled = isAttempt || !recordedTasks.length;
    taskChoice.disabled = !recordedTasks.length;
    attemptChoice.disabled = !recordedTasks.length;
    $("reviewTaskLabel").classList.toggle("hidden", isAttempt);
    submit.textContent = isAttempt ? "Отправить всю попытку" : "Отправить одно задание";
    submit.disabled = reviewRequestSent || !recordedTasks.length || !isStudent;
    if (!isStudent && !reviewRequestSent) message.textContent = "Войдите как ученик, чтобы отправить запись на разбор.";
    else if (!recordedTasks.length && !reviewRequestSent) message.textContent = "Нет задания с полным комплектом аудиозаписей для отправки.";
    else if (!reviewRequestSent && !message.hasChildNodes()) message.textContent = "";
  };
  taskChoice.onchange = update;
  attemptChoice.onchange = update;
  submit.onclick = async () => {
    const selection = attemptChoice.checked
      ? { kind: "attempt", tasks: [...recordedTasks] }
      : { kind: "task", tasks: [Number(taskSelect.value)] };
    submit.disabled = true;
    try {
      if (await account.submitReviewRequest(selection)) reviewRequestSent = true;
    } catch (_) {
      // Контроллер показывает ошибку и кнопку повтора непосредственно у выбора.
    } finally {
      update();
    }
  };
  update();
}

runner = createRunnerController({
  getVariant: () => variant,
  getProgress: () => progress,
  saveProgressLocal,
  showScreen,
  markTaskCompleted,
  finalizeActiveRun,
  toast,
  getAccount: () => account,
  onRunStarted: () => {
    reviewRequestSent = false;
    account?.clearPendingReviewRequest();
    $("reviewRequestMessage").textContent = "";
  },
  onRunFinished: () => {
    reviewRequestSent = false;
    renderReviewRequestChooser();
    account?.archiveCompletedRun(runner.getCompletedRun(), runner.getCompletedRecordings());
  },
});
const {
  startRun, ensureMicrophone, startPreparation, skipPhase, exitRun,
} = runner;

account = createAccountController({
  toast, switchProgressScope, renderProgress,
  getProgress: () => progress,
  getProgressStorageKey: () => progressStorageKey,
  setProgress: (value) => { progress = value; },
  saveProgressLocal,
  loadVariant,
  getVariant: () => variant,
  startRun,
  getVariantIndex: () => variantIndex,
  refreshMaterials: initVariants,
  getCompletedRecordings: () => runner.getCompletedRecordings(),
  getCompletedTasks: () => runner.getCompletedTasks(),
  getCompletedRun: () => runner.getCompletedRun(),
  setArchiveStatus: (message, canRetry) => {
    $("submissionStatus").textContent = message;
    $("retryArchiveBtn").classList.toggle("hidden", !canRetry);
  },
  onReviewRequestSent: () => {
    reviewRequestSent = true;
    renderReviewRequestChooser();
  },
});
const {
  initAuth, setAuthMode, openModal, closeModal, submitAuth, logout, requestPasswordReset,
  submitPasswordReset, cancelPasswordReset, sendVerificationEmail,
  loadAuditLog, deleteAccount, handleAccountLinks,
  saveReviewScores, showStudentReviewHistory, loadTeacherReviewRequests,
  discardUploadingReviewRequest,
} = account;

document.querySelectorAll("[data-start]").forEach(button => button.addEventListener("click", () => startRun(button.dataset.start)));
$("variantSelect").addEventListener("change", event => {
  progress.settings.lastVariant = event.target.value;
  saveProgressLocal();
  loadVariant(event.target.value);
});
$("fastMode").addEventListener("change", event => {
  progress.settings.fastMode = event.target.checked;
  saveProgressLocal();
});
$("checkMicBtn").addEventListener("click", () => ensureMicrophone(true));
$("mainActionBtn").addEventListener("click", startPreparation);
$("skipBtn").addEventListener("click", skipPhase);
$("exitBtn").addEventListener("click", exitRun);
$("restartBtn").addEventListener("click", () => showScreen("home"));
$("retryArchiveBtn").addEventListener("click", () => account.retryArchive(runner.getCompletedRun()));
$("authButton").addEventListener("click", () => openModal($("authModal")));
$("authCloseBtn").addEventListener("click", () => closeModal($("authModal")));
$("progressCloseBtn").addEventListener("click", () => closeModal($("progressModal")));
$("teacherCloseBtn").addEventListener("click", () => closeModal($("teacherModal")));
$("openProgressBtn").addEventListener("click", () => { renderHistory(); account.loadPersonalRecordings().catch(() => {}); openModal($("progressModal")); });
$("clearHistoryBtn").addEventListener("click", clearHistory);
$("loginTab").addEventListener("click", () => setAuthMode("login"));
$("registerTab").addEventListener("click", () => setAuthMode("register"));
$("authForm").addEventListener("submit", submitAuth);
$("forgotPasswordBtn").addEventListener("click", requestPasswordReset);
$("passwordResetForm").addEventListener("submit", submitPasswordReset);
$("cancelPasswordResetBtn").addEventListener("click", cancelPasswordReset);
$("sendVerificationBtn").addEventListener("click", sendVerificationEmail);
$("showAuditBtn").addEventListener("click", loadAuditLog);
$("showDeleteAccountBtn").addEventListener("click", () => $("deleteAccountForm").classList.toggle("hidden"));
$("deleteAccountForm").addEventListener("submit", deleteAccount);
$("teacherReviewRequests").addEventListener("submit", event => {
  const form = event.target.closest("[data-review-request]");
  if (!form) return;
  event.preventDefault();
  saveReviewScores(form);
});
$("teacherReviewRequests").addEventListener("click", event => {
  const button = event.target.closest("[data-student-review-history]");
  if (button) showStudentReviewHistory(Number(button.dataset.studentReviewHistory));
});
$("studentReviewRequestsList").addEventListener("click", event => {
  const button = event.target.closest("[data-discard-review-request]");
  if (button) discardUploadingReviewRequest(Number(button.dataset.discardReviewRequest));
});
$("reviewRequestFilters").addEventListener("submit", event => { event.preventDefault(); loadTeacherReviewRequests(); });
$("teacherCabinetBtn").addEventListener("click", async () => { await loadTeacherReviewRequests(); closeModal($("authModal")); openModal($("teacherModal")); });
$("logoutBtn").addEventListener("click", logout);
[$("authModal"), $("progressModal"), $("teacherModal")].forEach(modal => modal.addEventListener("click", event => {
  if (event.target === modal) closeModal(modal);
}));
document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    closeModal($("authModal"));
    closeModal($("progressModal"));
    closeModal($("teacherModal"));
  }
});
$("soundToggle").addEventListener("click", runner.toggleSound);

window.addEventListener("beforeunload", runner.cleanup);

renderProgress();
setAuthMode("login");

async function initialize() {
  enhanceProjectSelects();
  enhanceMaterialList($("variantSelect"), $("materialList"));
  await initVariants();
  await handleAccountLinks();
  await initAuth();
  recoverInterruptedRun();
  renderProgress();
  const url = new URL(window.location.href);
  if (url.searchParams.get("account") === "1") {
    openModal($("authModal"));
    url.searchParams.delete("account");
    window.history.replaceState({}, "", url);
  }
}

initialize();
