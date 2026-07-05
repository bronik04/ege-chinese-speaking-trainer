import { createRunnerController } from "./js/runner-controller.js";
import {
  PROGRESS_ACCOUNT_PREFIX, PROGRESS_GUEST_KEY, defaultProgress,
  escapeHtml, formatHistoryDate, loadLocalProgress,
} from "./js/progress.js";
import { shortTime } from "./js/task-view.js";
import { createAccountController } from "./js/account-controller.js";

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
let account = null;
let runner = null;

const taskData = (task) => variant.tasks[String(task)];

function showScreen(name) {
  Object.entries(screens).forEach(([key, node]) => node.classList.toggle("hidden", key !== name));
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
  $("progressSummary").textContent = completed.length ? `${completed.length} тренировок · ${tasks} заданий` : "Тренировок пока нет";
  $("progressSyncStatus").textContent = account?.user
    ? `Синхронизировано · ${account.user.email}`
    : latest ? `Последняя: ${formatHistoryDate(latest.completedAt || latest.startedAt)}` : "Сохраняется в этом браузере";
  $("accountRuns").textContent = completed.length;
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
  if (!progress.activeRun) return;
  progress.runs.unshift({ ...progress.activeRun, status: "interrupted", completedAt: new Date().toISOString(), recordingsCount: 0 });
  progress.activeRun = null;
  saveProgressLocal(false);
}

function clearHistory() {
  if (!confirm("Удалить всю историю тренировок? Это действие нельзя отменить.")) return;
  progress.runs = [];
  progress.activeRun = null;
  saveProgressLocal();
  closeModal($("progressModal"));
  toast("История очищена");
}

function setStartButtonsEnabled(enabled) {
  document.querySelectorAll("[data-start]").forEach(button => { button.disabled = !enabled; });
}

async function initVariants() {
  try {
    const response = await fetch("data/variants/index.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    variantIndex = await response.json();
    $("variantCount").textContent = variantIndex.length;
    $("variantSelect").innerHTML = variantIndex.map(item => `<option value="${item.id}">${item.label}</option>`).join("");
    const preferredVariant = variantIndex.some(item => item.id === progress.settings.lastVariant)
      ? progress.settings.lastVariant
      : variantIndex[0].id;
    $("variantSelect").value = preferredVariant;
    $("fastMode").checked = Boolean(progress.settings.fastMode);
    await loadVariant(preferredVariant);
    if (account?.user?.role === "teacher") account.renderAssignmentOptions();
  } catch (error) {
    $("variantSource").textContent = "Не удалось загрузить задания";
    toast("Запустите проект через локальный сервер");
    console.error("Variant loading failed", error);
  }
}

async function loadVariant(id) {
  setStartButtonsEnabled(false);
  const item = variantIndex.find(entry => entry.id === id);
  if (!item) return;
  try {
    if (!variantCache.has(id)) {
      const response = await fetch(item.file);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      variantCache.set(id, await response.json());
    }
    variant = variantCache.get(id);
    updateVariantUI();
    setStartButtonsEnabled(true);
  } catch (error) {
    toast("Не удалось загрузить выбранный вариант");
    console.error("Variant loading failed", error);
  }
}

function updateVariantUI() {
  $("heroVariant").textContent = `ЕГЭ · ${variant.label}`;
  $("variantSource").textContent = variant.source;
  $("totalMinutes").textContent = variant.totalMinutes;
  $("task1Timing").textContent = `${shortTime(taskData(1).prepSeconds)} + 5 × ${shortTime(taskData(1).answerSeconds)}`;
  $("task2Timing").textContent = `${shortTime(taskData(2).prepSeconds)} + до ${shortTime(taskData(2).answerSeconds)}`;
  $("task3Timing").textContent = `${shortTime(taskData(3).prepSeconds)} + до ${shortTime(taskData(3).answerSeconds)}`;
  $("task3CardTitle").firstChild.textContent = taskData(3).title.startsWith("Сравнение") ? "Сравнение фото" : "Проектная работа";
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
});
const {
  initAuth, setAuthMode, openModal, closeModal, submitAuth, logout, requestPasswordReset,
  submitPasswordReset, cancelPasswordReset, sendVerificationEmail,
  loadAuditLog, deleteAccount, handleAccountLinks, joinGroup, createGroup,
  createAssignment, submitReview, showAttemptHistory, handleAssignmentAction,
  loadTeacherDashboard, loadTeacherSubmissions, loadTeacherAssignments,
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
$("restartBtn").addEventListener("click", () => { runner.resetAssignment(); showScreen("home"); });
$("authButton").addEventListener("click", () => openModal($("authModal")));
$("authCloseBtn").addEventListener("click", () => closeModal($("authModal")));
$("progressCloseBtn").addEventListener("click", () => closeModal($("progressModal")));
$("teacherCloseBtn").addEventListener("click", () => closeModal($("teacherModal")));
$("openProgressBtn").addEventListener("click", () => { renderHistory(); openModal($("progressModal")); });
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
$("joinGroupForm").addEventListener("submit", joinGroup);
$("createGroupForm").addEventListener("submit", createGroup);
$("createAssignmentForm").addEventListener("submit", createAssignment);
$("teacherSubmissions").addEventListener("submit", submitReview);
$("teacherSubmissions").addEventListener("click", showAttemptHistory);
$("teacherAssignments").addEventListener("click", event => handleAssignmentAction(event).catch(error => toast(error.message)));
$("submissionFilters").addEventListener("submit", event => { event.preventDefault(); loadTeacherSubmissions(); });
$("teacherCabinetBtn").addEventListener("click", async () => { await Promise.all([loadTeacherDashboard(), loadTeacherSubmissions(), loadTeacherAssignments()]); closeModal($("authModal")); openModal($("teacherModal")); });
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

recoverInterruptedRun();
renderProgress();
setAuthMode("login");

async function initialize() {
  await initVariants();
  await handleAccountLinks();
  await initAuth();
}

initialize();
