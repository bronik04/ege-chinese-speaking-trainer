import { createRunnerController } from "./runner-controller.js";
import { defaultProgress, formatHistoryDate, loadLocalProgress, progressStorageKeys } from "../shared/progress.js";
import { shortTime } from "./task-view.js";
import { plural, pluralize } from "../shared/plural.js";
import { createAccountController } from "../account/account-controller.js";
import { fullyRecordedTasks } from "../account/account-review-requests-controller.js";
import { prepareRunResume } from "./resume-run.js";
import { buildReadinessSummary } from "./readiness.js";
import "../shared/site-shell.js";

const $ = (id) => document.getElementById(id);

const screens = {
  home: $("homeScreen"),
  readiness: $("readinessScreen"),
  runner: $("runnerScreen"),
  result: $("resultScreen")
};

let variantIndex = [];
let variant = null;
let variantCatalogScope = null;
let variantCatalogGeneration = 0;
let variantLoadGeneration = 0;
const variantCache = new Map();
let progressScope = progressStorageKeys();
let progress = loadLocalProgress(progressScope, { onError: message => toast(message) });
let account = null;
let runner = null;
let reviewRequestSent = false;
let pendingRunStart = null;
let readinessGeneration = 0;
let readinessMicReady = false;
let readinessStartPending = false;

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
  const nextScope = progressStorageKeys(user?.id);
  if (nextScope.current === progressScope.current) return;
  const readinessWasOpen = !screens.readiness.classList.contains("hidden");
  const hasScopedProgress = localStorage.getItem(nextScope.current) !== null
    || localStorage.getItem(nextScope.legacy) !== null;
  if (user && adoptGuest && !hasScopedProgress && progressScope.current === progressStorageKeys().current) {
    const guestProgress = loadLocalProgress(progressScope, { onError: message => toast(message) });
    const shouldTransfer = guestProgress.runs.length > 0 || Boolean(guestProgress.activeRun);
    progress = shouldTransfer ? guestProgress : defaultProgress();
    if (shouldTransfer) {
      try {
        localStorage.setItem(nextScope.current, JSON.stringify(progress));
        localStorage.removeItem(progressScope.current);
        localStorage.removeItem(progressScope.legacy);
      } catch (_) {
        toast("Не удалось перенести прогресс в аккаунт");
        progress = loadLocalProgress(nextScope, { onError: message => toast(message) });
      }
    }
  } else {
    progress = loadLocalProgress(nextScope, { onError: message => toast(message) });
  }
  progressScope = nextScope;
  variantCatalogGeneration += 1;
  variantLoadGeneration += 1;
  variantCatalogScope = null;
  variantCache.clear();
  variant = null;
  setStartButtonsEnabled(false);
  resetReadiness();
  if (readinessWasOpen) showScreen("home");
  $("resumeRunPanel").classList.add("hidden");
}

function saveProgressLocal(sync = true) {
  progress.updatedAt = new Date().toISOString();
  progress.runs = progress.runs.slice(0, 100);
  localStorage.setItem(progressScope.current, JSON.stringify(progress));
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
    ? account.progressHydrated
      ? `Синхронизировано · ${account.user.email}`
      : "Нет связи · сохранено в браузере"
    : latest ? `Последняя: ${formatHistoryDate(latest.completedAt || latest.startedAt)}` : "Сохраняется в этом браузере";
  $("accountRuns").textContent = completed.length;
  $("accountRunsLabel").textContent = plural(completed.length, "завершённая тренировка", "завершённые тренировки", "завершённых тренировок");
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

function setStartButtonsEnabled(enabled) {
  document.querySelectorAll("[data-start]").forEach(button => {
    const unavailableForTask = variant?.kind === "task" && button.dataset.start !== String(variant.taskNumber);
    button.disabled = !enabled || unavailableForTask;
  });
}

async function initVariants() {
  const expectedScope = progressScope.current;
  const requestGeneration = ++variantCatalogGeneration;
  try {
    const response = await fetch("/api/materials");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (expectedScope !== progressScope.current || requestGeneration !== variantCatalogGeneration) return false;
    variantIndex = payload.materials;
    variantCatalogScope = expectedScope;
    $("variantCount").textContent = variantIndex.length;
    $("variantCountLabel").textContent = plural(variantIndex.length, "вариант", "варианта", "вариантов");
    const requestedVariant = new URLSearchParams(window.location.search).get("variant");
    const preferredVariant = variantIndex.some(item => item.id === requestedVariant)
      ? requestedVariant
      : variantIndex.some(item => item.id === progress.settings.lastVariant)
        ? progress.settings.lastVariant
        : variantIndex[0].id;
    await loadVariant(preferredVariant);
    return true;
  } catch (error) {
    if (expectedScope !== progressScope.current || requestGeneration !== variantCatalogGeneration) return false;
    $("variantSource").textContent = "Не удалось загрузить задания";
    toast("Запустите проект через локальный сервер");
    console.error("Variant loading failed", error);
    return false;
  }
}

async function loadVariant(id, snapshot = null) {
  const expectedScope = progressScope.current;
  const requestGeneration = ++variantLoadGeneration;
  setStartButtonsEnabled(false);
  const item = variantIndex.find(entry => entry.id === id);
  if (!item && !snapshot) {
    if (variant) setStartButtonsEnabled(true);
    return false;
  }
  try {
    if (snapshot) variantCache.set(id, snapshot);
    if (!variantCache.has(id)) {
      const response = await fetch(`/api/materials/${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const material = (await response.json()).material;
      if (expectedScope !== progressScope.current || requestGeneration !== variantLoadGeneration) return false;
      variantCache.set(id, material);
    }
    if (expectedScope !== progressScope.current || requestGeneration !== variantLoadGeneration) return false;
    variant = variantCache.get(id);
    const canPersistSelection = !account?.user || account.progressHydrated;
    if (progress.settings.lastVariant !== id && canPersistSelection) {
      progress.settings.lastVariant = id;
      saveProgressLocal();
    }
    const url = new URL(window.location.href);
    url.searchParams.set("variant", id);
    window.history.replaceState({}, "", url);
    updateVariantUI();
    return true;
  } catch (error) {
    if (expectedScope !== progressScope.current || requestGeneration !== variantLoadGeneration) return false;
    toast("Не удалось загрузить выбранный вариант");
    console.error("Variant loading failed", error);
    return false;
  } finally {
    if (expectedScope === progressScope.current && requestGeneration === variantLoadGeneration && variant) {
      setStartButtonsEnabled(true);
    }
  }
}

function updateVariantUI() {
  $("selectedMaterialTitle").textContent = variant.label;
  $("variantSource").textContent = variant.source;
  $("selectedMaterialDuration").textContent = pluralize(variant.totalMinutes, "минута", "минуты", "минут");
  $("totalMinutes").textContent = variant.totalMinutes;
  $("totalMinutesLabel").textContent = plural(variant.totalMinutes, "минута", "минуты", "минут");
  if (taskData(1)) $("task1Timing").textContent = `${shortTime(taskData(1).prepSeconds)} + 5 × ${shortTime(taskData(1).answerSeconds)}`;
  if (taskData(2)) $("task2Timing").textContent = `${shortTime(taskData(2).prepSeconds)} + до ${shortTime(taskData(2).answerSeconds)}`;
  if (taskData(3)) {
    $("task3Timing").textContent = `${shortTime(taskData(3).prepSeconds)} + до ${shortTime(taskData(3).answerSeconds)}`;
    $("task3CardTitle").firstChild.textContent = taskData(3).title.startsWith("Сравнение") ? "Сравнение фото" : "Проектная работа";
  }
}

function renderResumeRunOffer() {
  const panel = $("resumeRunPanel");
  const storedRun = progress.activeRun;
  if (!storedRun || !variantIndex.length || variantCatalogScope !== progressScope.current) {
    panel.classList.add("hidden");
    return;
  }
  if (!variantIndex.some(item => item.id === storedRun.variantId)) {
    finalizeActiveRun("interrupted", 0);
    panel.classList.add("hidden");
    toast("Незавершённый вариант больше недоступен. Попытка сохранена в истории");
    return;
  }
  const resumedRun = prepareRunResume(storedRun);
  const modeLabel = resumedRun.mode === "exam" ? "Экзамен" : "Тренировка";
  $("resumeRunDetails").textContent = `${resumedRun.variantLabel} · ${modeLabel} · Задание ${resumedRun.currentTask}`;
  panel.classList.remove("hidden");
}

async function checkReadinessMicrophone() {
  const generation = readinessGeneration;
  readinessMicReady = false;
  $("beginReadyRunBtn").disabled = true;
  $("retryReadinessMicBtn").disabled = true;
  $("readinessMicDot").className = "status-dot";
  $("readinessMicStatus").textContent = "Проверяем доступ…";
  const ready = await runner.ensureMicrophone(false);
  if (generation !== readinessGeneration || !pendingRunStart) return;
  readinessMicReady = ready;
  $("readinessMicDot").className = `status-dot ${ready ? "ok" : "bad"}`;
  $("readinessMicStatus").textContent = ready ? "Микрофон готов" : "Нет доступа к микрофону";
  $("beginReadyRunBtn").disabled = !ready;
  $("retryReadinessMicBtn").disabled = false;
}

function openReadiness({ kind, startMode, storedRun = null }) {
  if (!variant) return;
  readinessGeneration += 1;
  pendingRunStart = { kind, startMode, runId: storedRun?.id || null, scope: progressScope.current };
  const summary = buildReadinessSummary({ variant, pending: pendingRunStart, activeRun: storedRun });
  $("readinessMaterial").textContent = summary.material;
  $("readinessMode").textContent = summary.mode;
  $("readinessTasks").textContent = summary.tasks;
  $("readinessDuration").textContent = summary.duration;
  $("beginReadyRunBtn").textContent = summary.action;
  showScreen("readiness");
  checkReadinessMicrophone();
}

function resetReadiness() {
  readinessGeneration += 1;
  pendingRunStart = null;
  readinessMicReady = false;
  readinessStartPending = false;
  $("beginReadyRunBtn").disabled = true;
}

function cancelReadiness() {
  resetReadiness();
  showScreen("home");
  renderResumeRunOffer();
}

async function beginReadyRun() {
  if (!pendingRunStart || !readinessMicReady || readinessStartPending) return;
  const pending = pendingRunStart;
  const generation = readinessGeneration;
  readinessStartPending = true;
  $("beginReadyRunBtn").disabled = true;
  try {
    const microphoneReady = await runner.ensureMicrophone(false);
    if (generation !== readinessGeneration || pendingRunStart !== pending) return;
    if (!microphoneReady) {
      readinessMicReady = false;
      $("readinessMicDot").className = "status-dot bad";
      $("readinessMicStatus").textContent = "Нет доступа к микрофону";
      return;
    }
    if (pending.scope !== progressScope.current) return cancelReadiness();
    if (pending.kind !== "new") {
      const storedRun = progress.activeRun;
      if (!storedRun || storedRun.id !== pending.runId) return cancelReadiness();
      if (!(await loadVariant(storedRun.variantId))) return;
      if (pending.scope !== progressScope.current || progress.activeRun?.id !== pending.runId) return cancelReadiness();
      if (pending.kind === "resume") runner.resumeRun(storedRun);
      else {
        finalizeActiveRun("interrupted", 0);
        runner.startRun(pending.startMode);
      }
    } else {
      if (progress.activeRun) finalizeActiveRun("interrupted", 0);
      runner.startRun(pending.startMode);
    }
    readinessGeneration += 1;
    pendingRunStart = null;
    readinessMicReady = false;
    $("resumeRunPanel").classList.add("hidden");
  } finally {
    readinessStartPending = false;
    if (pendingRunStart && readinessMicReady) $("beginReadyRunBtn").disabled = false;
  }
}

function continueInterruptedRun() {
  const storedRun = progress.activeRun;
  if (!storedRun) return;
  const resumedRun = prepareRunResume(storedRun);
  openReadiness({ kind: "resume", startMode: resumedRun.mode === "exam" ? "exam" : String(resumedRun.tasks[0]), storedRun });
}

function restartInterruptedRun() {
  const storedRun = progress.activeRun;
  if (!storedRun) return;
  const startMode = storedRun.mode === "exam" ? "exam" : String(storedRun.tasks[0]);
  openReadiness({ kind: "restart", startMode, storedRun });
}

function startNewRun(startMode) {
  openReadiness({ kind: "new", startMode });
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
  getProgressStorageKey: () => progressScope.current,
  setProgress: (value) => { progress = value; },
  saveProgressLocal,
  getVariant: () => variant,
  startRun,
  refreshMaterials: async () => {
    if (await initVariants()) renderResumeRunOffer();
  },
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
  handleAccountLinks,
} = account;

document.querySelectorAll("[data-start]").forEach(button => button.addEventListener("click", () => startNewRun(button.dataset.start)));
$("checkMicBtn").addEventListener("click", () => ensureMicrophone(true));
$("continueRunBtn").addEventListener("click", continueInterruptedRun);
$("restartInterruptedRunBtn").addEventListener("click", restartInterruptedRun);
$("cancelReadyRunBtn").addEventListener("click", cancelReadiness);
$("retryReadinessMicBtn").addEventListener("click", checkReadinessMicrophone);
$("beginReadyRunBtn").addEventListener("click", beginReadyRun);
$("mainActionBtn").addEventListener("click", startPreparation);
$("skipBtn").addEventListener("click", skipPhase);
$("exitBtn").addEventListener("click", exitRun);
$("restartBtn").addEventListener("click", () => showScreen("home"));
$("downloadAllRecordingsBtn").addEventListener("click", runner.downloadRecordingsArchive);
$("retryArchiveBtn").addEventListener("click", () => account.retryArchive());
$("authButton").addEventListener("click", () => openModal($("authModal")));
$("authCloseBtn").addEventListener("click", () => closeModal($("authModal")));
$("loginTab").addEventListener("click", () => setAuthMode("login"));
$("registerTab").addEventListener("click", () => setAuthMode("register"));
$("authForm").addEventListener("submit", submitAuth);
$("forgotPasswordBtn").addEventListener("click", requestPasswordReset);
$("passwordResetForm").addEventListener("submit", submitPasswordReset);
$("cancelPasswordResetBtn").addEventListener("click", cancelPasswordReset);
$("sendVerificationBtn").addEventListener("click", sendVerificationEmail);
$("logoutBtn").addEventListener("click", logout);
$("authModal").addEventListener("click", event => {
  if (event.target === $("authModal")) closeModal($("authModal"));
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    closeModal($("authModal"));
  }
});
$("soundToggle").addEventListener("click", runner.toggleSound);

window.addEventListener("beforeunload", runner.cleanup);

renderProgress();
setAuthMode("login");

async function initialize() {
  await initVariants();
  await handleAccountLinks();
  await initAuth();
  renderResumeRunOffer();
  renderProgress();
  const url = new URL(window.location.href);
  if (url.searchParams.get("account") === "1") {
    openModal($("authModal"));
    url.searchParams.delete("account");
    window.history.replaceState({}, "", url);
  }
}

initialize();
