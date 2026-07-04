import { api, uploadAudio } from "./js/api.js";
import {
  PROGRESS_ACCOUNT_PREFIX, PROGRESS_GUEST_KEY, createRunId, defaultProgress,
  escapeHtml, formatHistoryDate, loadLocalProgress, mergeProgress,
} from "./js/progress.js";
import { collectReviewScores } from "./js/review.js";
import {
  assignmentOptionsMarkup, studentAssignmentsMarkup, studentGroupsMarkup,
  teacherGroupsMarkup, teacherSubmissionsMarkup,
} from "./js/account-view.js";
import { formatTime, shortTime, stepsMarkup, taskMarkup } from "./js/task-view.js";
import { auditMarkup } from "./js/account-security.js";

const $ = (id) => document.getElementById(id);

const screens = {
  home: $("homeScreen"),
  runner: $("runnerScreen"),
  result: $("resultScreen")
};

let variantIndex = [];
let variant = null;
const variantCache = new Map();
let mode = "exam";
let taskQueue = [];
let taskIndex = 0;
let phase = "idle";
let questionIndex = 0;
let selectedPhoto = 1;
let photoChoiceMade = false;
let timerId = null;
let deadline = 0;
let phaseDuration = 0;
let stream = null;
let recorder = null;
let chunks = [];
let recordings = [];
let soundEnabled = true;
let audioContext = null;
let progressStorageKey = PROGRESS_GUEST_KEY;
let progress = loadLocalProgress(progressStorageKey);
let authUser = null;
let authMode = "login";
let syncTimer = null;
let studentAssignments = [];
let activeAssignment = null;
let teacherGroupsData = [];
let passwordResetToken = new URLSearchParams(window.location.search).get("reset");

const taskData = (task) => variant.tasks[String(task)];

const durationFor = (task, kind) => {
  if (!$("fastMode").checked) return taskData(task)[`${kind}Seconds`];
  if (task === 1) return kind === "prep" ? 8 : 5;
  return kind === "prep" ? 8 : 10;
};

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
  if (sync && authUser) scheduleProgressSync();
}

function renderProgress() {
  const completed = progress.runs.filter(run => run.status === "completed");
  const tasks = completed.reduce((sum, run) => sum + (run.completedTasks?.length || 0), 0);
  const latest = progress.runs[0];
  $("progressSummary").textContent = completed.length ? `${completed.length} тренировок · ${tasks} заданий` : "Тренировок пока нет";
  $("progressSyncStatus").textContent = authUser
    ? `Синхронизировано · ${authUser.email}`
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

function finalizeActiveRun(status) {
  if (!progress.activeRun) return;
  progress.runs.unshift({
    ...progress.activeRun,
    status,
    completedAt: new Date().toISOString(),
    recordingsCount: recordings.length
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

async function initAuth() {
  try {
    const payload = await api("/api/auth/me");
    authUser = payload.user;
    switchProgressScope(authUser);
    renderAuth();
  } catch (error) {
    authUser = null;
    switchProgressScope(null);
    renderAuth();
    if (error.status !== 401) $("progressSyncStatus").textContent = "Сервер недоступен · локальное сохранение";
    return;
  }
  try { await syncProgress(); } catch (_) { $("progressSyncStatus").textContent = "Нет связи · сохранено в браузере"; }
  try { await refreshAccountData(); } catch (_) {}
}

function renderAuth() {
  const resettingPassword = Boolean(passwordResetToken);
  $("authButton").classList.toggle("signed-in", Boolean(authUser));
  $("authButtonText").textContent = authUser ? authUser.email : "Войти";
  $("authGuestView").classList.toggle("hidden", Boolean(authUser) || resettingPassword);
  $("authUserView").classList.toggle("hidden", !authUser || resettingPassword);
  $("passwordResetView").classList.toggle("hidden", !resettingPassword);
  $("authUserEmail").textContent = authUser?.email || "";
  $("authUserName").textContent = authUser?.displayName || "";
  const isTeacher = authUser?.role === "teacher";
  $("accountRole").textContent = isTeacher ? "Преподаватель" : "Ученик";
  $("accountTitle").textContent = isTeacher ? "Ваши ученики и группы" : "Прогресс синхронизирован";
  $("studentAccountTools").classList.toggle("hidden", !authUser || isTeacher);
  $("teacherCabinetBtn").classList.toggle("hidden", !isTeacher);
  $("emailVerificationPanel").classList.toggle("hidden", !authUser || authUser.emailVerified);
  if (!authUser) {
    studentAssignments = [];
    teacherGroupsData = [];
    $("studentAssignmentsPanel").classList.add("hidden");
    $("studentAssignmentsList").innerHTML = "";
    $("studentGroups").innerHTML = "";
  }
  renderProgress();
}

function setAuthMode(nextMode) {
  authMode = nextMode;
  $("loginTab").classList.toggle("active", authMode === "login");
  $("registerTab").classList.toggle("active", authMode === "register");
  $("authSubmitBtn").textContent = authMode === "login" ? "Войти" : "Создать аккаунт";
  $("authPassword").autocomplete = authMode === "login" ? "current-password" : "new-password";
  document.querySelectorAll(".register-only").forEach(element => element.classList.toggle("hidden", authMode !== "register"));
  $("authName").required = authMode === "register";
  $("authMessage").textContent = "";
}

function openModal(modal) {
  modal.classList.remove("hidden");
  document.body.classList.add("modal-open");
}

function closeModal(modal) {
  modal.classList.add("hidden");
  if ($("authModal").classList.contains("hidden") && $("progressModal").classList.contains("hidden") && $("teacherModal").classList.contains("hidden")) document.body.classList.remove("modal-open");
}

async function submitAuth(event) {
  event.preventDefault();
  const email = $("authEmail").value.trim();
  const password = $("authPassword").value;
  const displayName = $("authName").value.trim();
  const role = $("authRole").value;
  $("authSubmitBtn").disabled = true;
  $("authMessage").textContent = "";
  try {
    const payload = await api(`/api/auth/${authMode}`, { method: "POST", body: JSON.stringify({ email, password, displayName, role }) });
    authUser = payload.user;
    switchProgressScope(authUser, { adoptGuest: authMode === "register" });
    renderAuth();
    try { await syncProgress(); } catch (_) { $("progressSyncStatus").textContent = "Нет связи · сохранено в браузере"; }
    try { await refreshAccountData(); } catch (_) {}
    closeModal($("authModal"));
    toast(authMode === "login" ? "Вход выполнен" : "Аккаунт создан");
    $("authForm").reset();
  } catch (error) {
    $("authMessage").textContent = error.message === "Failed to fetch" ? "Сервер недоступен. Запустите python3 server.py" : error.message;
  } finally {
    $("authSubmitBtn").disabled = false;
  }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } catch (_) {}
  clearTimeout(syncTimer);
  authUser = null;
  switchProgressScope(null);
  renderAuth();
  closeModal($("authModal"));
  toast("Вы вышли из аккаунта. Локальная история сохранена");
}

async function requestPasswordReset() {
  const emailInput = $("authEmail");
  if (!emailInput.reportValidity()) return;
  $("forgotPasswordBtn").disabled = true;
  try {
    const payload = await api("/api/auth/password/request", {
      method: "POST", body: JSON.stringify({ email: emailInput.value.trim() })
    });
    $("authMessage").textContent = payload.message;
  } catch (error) {
    $("authMessage").textContent = error.message;
  } finally {
    $("forgotPasswordBtn").disabled = false;
  }
}

async function submitPasswordReset(event) {
  event.preventDefault();
  try {
    await api("/api/auth/password/reset", {
      method: "POST",
      body: JSON.stringify({ token: passwordResetToken, password: $("passwordResetValue").value }),
    });
    passwordResetToken = null;
    window.history.replaceState({}, "", window.location.pathname);
    authUser = null;
    renderAuth();
    setAuthMode("login");
    $("authMessage").textContent = "Пароль изменён. Войдите с новым паролем.";
  } catch (error) {
    $("passwordResetMessage").textContent = error.message;
  }
}

function cancelPasswordReset() {
  passwordResetToken = null;
  window.history.replaceState({}, "", window.location.pathname);
  renderAuth();
  setAuthMode("login");
}

async function sendVerificationEmail() {
  $("sendVerificationBtn").disabled = true;
  try {
    const payload = await api("/api/auth/email/request", { method: "POST", body: "{}" });
    $("accountSecurityMessage").textContent = payload.delivery === "outbox"
      ? "Локальная ссылка сохранена в var/outbox.log"
      : "Письмо отправлено. Проверьте почту.";
  } catch (error) {
    $("accountSecurityMessage").textContent = error.message;
  } finally {
    $("sendVerificationBtn").disabled = false;
  }
}

async function loadAuditLog() {
  const list = $("auditList");
  if (!list.classList.contains("hidden")) {
    list.classList.add("hidden");
    $("showAuditBtn").textContent = "Показать журнал действий";
    return;
  }
  try {
    const payload = await api("/api/account/audit");
    list.innerHTML = auditMarkup(payload.events);
    list.classList.remove("hidden");
    $("showAuditBtn").textContent = "Скрыть журнал действий";
  } catch (error) {
    $("accountSecurityMessage").textContent = error.message;
  }
}

async function deleteAccount(event) {
  event.preventDefault();
  if (!confirm("Удалить аккаунт, прогресс и все связанные аудиозаписи без возможности восстановления?")) return;
  try {
    await api("/api/account", {
      method: "DELETE", body: JSON.stringify({ password: $("deleteAccountPassword").value })
    });
    localStorage.removeItem(progressStorageKey);
    authUser = null;
    switchProgressScope(null);
    renderAuth();
    closeModal($("authModal"));
    toast("Аккаунт и связанные данные удалены");
  } catch (error) {
    $("accountSecurityMessage").textContent = error.message;
  }
}

async function handleAccountLinks() {
  const params = new URLSearchParams(window.location.search);
  const verificationToken = params.get("verify");
  if (verificationToken) {
    try {
      await api("/api/auth/email/confirm", {
        method: "POST", body: JSON.stringify({ token: verificationToken })
      });
      toast("Email успешно подтверждён");
    } catch (error) {
      toast(error.message);
    }
    params.delete("verify");
    const query = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }
  if (passwordResetToken) {
    renderAuth();
    openModal($("authModal"));
  }
}

async function refreshAccountData() {
  if (!authUser) return;
  if (authUser.role === "teacher") {
    await Promise.all([loadTeacherDashboard(), loadTeacherSubmissions()]);
  } else {
    await Promise.all([loadStudentGroups(), loadStudentAssignments()]);
  }
}

async function loadStudentGroups() {
  if (authUser?.role !== "student") return;
  try {
    const payload = await api("/api/student/groups");
    $("studentGroups").innerHTML = studentGroupsMarkup(payload.groups);
  } catch (_) {
    $("studentGroups").innerHTML = "";
  }
}

async function joinGroup(event) {
  event.preventDefault();
  const code = $("joinGroupCode").value.trim().toUpperCase();
  try {
    const payload = await api("/api/groups/join", { method: "POST", body: JSON.stringify({ code }) });
    $("joinGroupForm").reset();
    await Promise.all([loadStudentGroups(), loadStudentAssignments()]);
    toast(`Вы вступили в группу «${payload.group.name}»`);
  } catch (error) {
    toast(error.message);
  }
}

async function loadTeacherDashboard() {
  if (authUser?.role !== "teacher") return;
  try {
    const payload = await api("/api/teacher/dashboard");
    teacherGroupsData = payload.groups;
    renderTeacherGroups(payload.groups);
    renderAssignmentOptions();
  } catch (error) {
    $("teacherMessage").textContent = error.message;
  }
}

async function loadStudentAssignments() {
  if (authUser?.role !== "student") {
    $("studentAssignmentsPanel").classList.add("hidden");
    return;
  }
  try {
    const payload = await api("/api/student/assignments");
    studentAssignments = payload.assignments;
    $("studentAssignmentsPanel").classList.toggle("hidden", !studentAssignments.length);
    $("studentAssignmentsList").innerHTML = studentAssignmentsMarkup(studentAssignments);
    document.querySelectorAll("[data-start-assignment]").forEach(button => button.addEventListener("click", () => startAssignedRun(Number(button.dataset.startAssignment))));
  } catch (_) {
    $("studentAssignmentsPanel").classList.add("hidden");
  }
}

async function startAssignedRun(assignmentId) {
  const assignment = studentAssignments.find(item => item.id === assignmentId);
  if (!assignment) return;
  await loadVariant(assignment.variantId);
  if (variant?.id !== assignment.variantId) {
    toast("Не удалось загрузить вариант задания");
    return;
  }
  $("variantSelect").value = assignment.variantId;
  startRun(assignment.tasks.length === 3 ? "exam" : String(assignment.tasks[0]), assignment);
}

function renderAssignmentOptions() {
  const markup = assignmentOptionsMarkup(teacherGroupsData, variantIndex);
  $("assignmentGroup").innerHTML = markup.groups;
  $("assignmentVariant").innerHTML = markup.variants;
  $("createAssignmentBtn").disabled = !teacherGroupsData.length;
}

async function createAssignment(event) {
  event.preventDefault();
  const selected = $("assignmentTasks").value;
  const tasks = selected === "exam" ? [1, 2, 3] : [Number(selected)];
  const dueValue = $("assignmentDue").value;
  const dueAt = dueValue ? Math.floor(new Date(dueValue).getTime() / 1000) : null;
  try {
    await api("/api/teacher/assignments", { method: "POST", body: JSON.stringify({
      groupId: Number($("assignmentGroup").value), title: $("assignmentTitle").value.trim(),
      variantId: $("assignmentVariant").value, tasks, dueAt,
    }) });
    $("createAssignmentForm").reset();
    renderAssignmentOptions();
    toast("Задание назначено группе");
  } catch (error) {
    $("teacherMessage").textContent = error.message;
  }
}

async function loadTeacherSubmissions() {
  if (authUser?.role !== "teacher") return;
  try {
    const payload = await api("/api/teacher/submissions");
    renderTeacherSubmissions(payload.submissions);
  } catch (error) {
    $("teacherReviewMessage").textContent = error.message;
  }
}

function renderTeacherSubmissions(submissions) {
  $("teacherSubmissions").innerHTML = teacherSubmissionsMarkup(submissions);
}

async function submitReview(event) {
  const form = event.target.closest("[data-review-submission]");
  if (!form) return;
  event.preventDefault();
  const tasks = form.dataset.reviewTasks.split(",").map(Number);
  try {
    const payload = await api(`/api/submissions/${form.dataset.reviewSubmission}/review`, {
      method: "POST", body: JSON.stringify({ scores: collectReviewScores(form, tasks), comment: form.elements.comment.value.trim() })
    });
    toast(`Оценка сохранена: ${payload.review.total}/${payload.review.maximum}`);
    await loadTeacherSubmissions();
  } catch (error) {
    $("teacherReviewMessage").textContent = error.message;
  }
}

function renderTeacherGroups(groups) {
  $("teacherGroups").innerHTML = teacherGroupsMarkup(groups);
  if (!groups.length) return;
  document.querySelectorAll("[data-copy-code]").forEach(button => button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(button.dataset.copyCode);
    toast("Код группы скопирован");
  }));
}

async function createGroup(event) {
  event.preventDefault();
  $("teacherMessage").textContent = "";
  try {
    const payload = await api("/api/teacher/groups", { method: "POST", body: JSON.stringify({ name: $("groupName").value.trim() }) });
    $("createGroupForm").reset();
    await loadTeacherDashboard();
    toast(`Группа «${payload.group.name}» создана`);
  } catch (error) {
    $("teacherMessage").textContent = error.message;
  }
}

function scheduleProgressSync() {
  clearTimeout(syncTimer);
  $("progressSyncStatus").textContent = "Сохраняем на сервере…";
  syncTimer = setTimeout(() => pushProgress().catch(() => {
    $("progressSyncStatus").textContent = "Нет связи · сохранено в браузере";
  }), 350);
}

async function pushProgress() {
  if (!authUser) return;
  await api("/api/progress", { method: "PUT", body: JSON.stringify({ progress }) });
  $("progressSyncStatus").textContent = `Синхронизировано · ${authUser.email}`;
}

async function syncProgress() {
  if (!authUser) return;
  const payload = await api("/api/progress");
  progress = mergeProgress(progress, payload.progress);
  saveProgressLocal(false);
  await pushProgress();
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
    if (authUser?.role === "teacher") renderAssignmentOptions();
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

async function ensureMicrophone(showSuccess = false) {
  if (stream?.active) return true;
  if (!navigator.mediaDevices?.getUserMedia) {
    setMicState(false, "Запись не поддерживается браузером");
    return false;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    setMicState(true, "Микрофон готов");
    if (showSuccess) toast("Микрофон работает — можно начинать");
    return true;
  } catch (error) {
    setMicState(false, "Нет доступа к микрофону");
    toast("Разрешите доступ к микрофону в настройках браузера");
    return false;
  }
}

function setMicState(ok, text) {
  $("micDot").className = `status-dot ${ok ? "ok" : "bad"}`;
  $("micStatus").textContent = text;
}

function beep(frequency = 740, duration = .16) {
  if (!soundEnabled) return;
  try {
    audioContext ||= new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(.0001, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(.16, audioContext.currentTime + .015);
    gain.gain.exponentialRampToValueAtTime(.0001, audioContext.currentTime + duration);
    oscillator.connect(gain).connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + duration);
  } catch (_) {}
}

function renderSteps() {
  $("stepList").innerHTML = stepsMarkup(taskQueue, taskIndex);
}

function renderTask() {
  const task = taskQueue[taskIndex];
  const isLocked = phase === "idle";
  $("taskBadge").textContent = `Задание ${task}`;
  $("phaseCaption").textContent = phase === "answer" ? "Ответ" : phase === "prep" ? "Подготовка" : "До начала";
  $("modeLabel").textContent = `${variant.label} · ${mode === "exam" ? "экзамен" : mode === "assignment" ? "задание преподавателя" : "тренировка"}`;
  $("taskContent").innerHTML = taskMarkup(task, taskData(task), { phase, questionIndex, selectedPhoto, photoChoiceMade });
  $("taskPaper").classList.toggle("locked", isLocked);
  $("taskLock").setAttribute("aria-hidden", String(!isLocked));
  document.querySelectorAll("[data-photo]").forEach(button => button.addEventListener("click", () => {
    if (phase === "answer") return;
    selectedPhoto = Number(button.dataset.photo);
    photoChoiceMade = true;
    renderTask();
  }));
  renderSteps();
}

function startRun(startMode, assignment = null) {
  if (!variant) return;
  activeAssignment = assignment;
  mode = assignment ? "assignment" : startMode === "exam" ? "exam" : "practice";
  taskQueue = assignment ? [...assignment.tasks] : mode === "exam" ? [1, 2, 3] : [Number(startMode)];
  taskIndex = 0;
  questionIndex = 0;
  selectedPhoto = 1;
  photoChoiceMade = false;
  recordings.forEach(item => URL.revokeObjectURL(item.url));
  recordings = [];
  phase = "idle";
  clearTimer();
  progress.activeRun = {
    id: createRunId(),
    variantId: variant.id,
    variantLabel: variant.label,
    mode,
    tasks: [...taskQueue],
    completedTasks: [],
    currentTask: taskQueue[0],
    phase: "idle",
    fastMode: $("fastMode").checked,
    assignmentId: assignment?.id || null,
    startedAt: new Date().toISOString()
  };
  saveProgressLocal();
  showScreen("runner");
  renderTask();
  setIdleControls();
}

function setIdleControls() {
  const task = taskQueue[taskIndex];
  $("timerEyebrow").textContent = "Задание закрыто";
  $("timerValue").textContent = formatTime(durationFor(task, "prep"));
  $("timerHint").textContent = "на подготовку";
  $("timerRing").style.setProperty("--progress", 1);
  $("timerRing").classList.remove("urgent");
  $("mainActionBtn").textContent = taskIndex ? "Открыть и начать подготовку" : "Начать подготовку";
  $("mainActionBtn").disabled = false;
  $("mainActionBtn").classList.remove("hidden");
  $("skipBtn").classList.add("hidden");
  setRecordingIndicator(false);
}

function startPreparation() {
  phase = "prep";
  if (progress.activeRun) {
    progress.activeRun.phase = phase;
    progress.activeRun.currentTask = taskQueue[taskIndex];
    saveProgressLocal();
  }
  renderTask();
  $("timerEyebrow").textContent = "Время на подготовку";
  $("timerHint").textContent = "до начала записи";
  $("mainActionBtn").classList.add("hidden");
  $("skipBtn").textContent = "Перейти к ответу";
  $("skipBtn").classList.remove("hidden");
  startTimer(durationFor(taskQueue[taskIndex], "prep"), beginAnswer);
}

async function beginAnswer() {
  clearTimer();
  beep(820, .22);
  phase = "answer";
  if (progress.activeRun) {
    progress.activeRun.phase = phase;
    progress.activeRun.currentTask = taskQueue[taskIndex];
    saveProgressLocal();
  }
  renderTask();
  $("timerEyebrow").textContent = taskQueue[taskIndex] === 1 ? `Вопрос ${questionIndex + 1} из 5` : "Время ответа";
  $("timerHint").textContent = "идёт запись";
  $("skipBtn").textContent = taskQueue[taskIndex] === 1 && questionIndex < 4 ? "Следующий вопрос" : "Завершить ответ";
  $("skipBtn").classList.remove("hidden");
  await startRecording();
  startTimer(durationFor(taskQueue[taskIndex], "answer"), finishAnswerPart);
}

async function startRecording() {
  const ready = await ensureMicrophone(false);
  if (!ready) {
    setRecordingIndicator(false, "Таймер идёт без записи");
    return;
  }
  if (typeof MediaRecorder === "undefined") {
    setRecordingIndicator(false, "Запись не поддерживается браузером");
    return;
  }
  try {
    chunks = [];
    const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(type => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined);
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.start();
    setRecordingIndicator(true);
  } catch (_) {
    recorder = null;
    setRecordingIndicator(false, "Не удалось начать запись");
  }
}

function stopRecording(label, task = taskQueue[taskIndex], question = null) {
  return new Promise(resolve => {
    if (!recorder || recorder.state === "inactive") return resolve();
    const current = recorder;
    current.onstop = () => {
      const type = current.mimeType || "audio/webm";
      const blob = new Blob(chunks, { type });
      if (blob.size) recordings.push({ label, task, question, blob, url: URL.createObjectURL(blob), type });
      setRecordingIndicator(false);
      resolve();
    };
    current.stop();
  });
}

async function finishAnswerPart() {
  clearTimer();
  const task = taskQueue[taskIndex];
  const label = task === 1 ? `${variant.label} · задание 1 · вопрос ${questionIndex + 1}` : `${variant.label} · задание ${task}`;
  await stopRecording(label, task, task === 1 ? questionIndex + 1 : null);
  beep(560, .2);
  if (task === 1 && questionIndex < 4) {
    questionIndex += 1;
    beginAnswer();
    return;
  }
  await advanceTask();
}

async function advanceTask() {
  clearTimer();
  markTaskCompleted(taskQueue[taskIndex]);
  if (taskIndex < taskQueue.length - 1) {
    taskIndex += 1;
    questionIndex = 0;
    selectedPhoto = 1;
    photoChoiceMade = false;
    phase = "idle";
    renderTask();
    setIdleControls();
  } else {
    await finishRun();
  }
}

function startTimer(seconds, onComplete) {
  clearTimer();
  phaseDuration = seconds;
  deadline = Date.now() + seconds * 1000;
  const tick = () => {
    const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    $("timerValue").textContent = formatTime(left);
    $("timerRing").style.setProperty("--progress", left / phaseDuration);
    $("timerRing").classList.toggle("urgent", left <= 10);
    if (left <= 0) {
      clearTimer();
      onComplete();
    }
  };
  tick();
  timerId = setInterval(tick, 250);
}

function clearTimer() {
  if (timerId) clearInterval(timerId);
  timerId = null;
}

function setRecordingIndicator(live, text) {
  $("recordingState").classList.toggle("live", live);
  $("recordingState").querySelector("b").textContent = text || (live ? "Идёт запись" : "Запись не идёт");
}

async function skipPhase() {
  if (phase === "prep") return beginAnswer();
  if (phase === "answer") return finishAnswerPart();
}

async function finishRun() {
  clearTimer();
  phase = "done";
  finalizeActiveRun("completed");
  renderRecordings();
  showScreen("result");
  if (activeAssignment && authUser?.role === "student") {
    $("submissionStatus").textContent = "Отправляем работу преподавателю…";
    try {
      const payload = await api(`/api/assignments/${activeAssignment.id}/submissions`, {
        method: "POST", body: JSON.stringify({ run: progress.runs[0] })
      });
      for (const recording of recordings) await uploadAudio(payload.submission.id, recording);
      $("submissionStatus").textContent = `Работа отправлена · попытка ${payload.submission.attempt}`;
      toast("Работа и аудиозаписи отправлены преподавателю");
      await loadStudentAssignments();
    } catch (error) {
      $("submissionStatus").textContent = `Не удалось отправить: ${error.message}. Записи доступны ниже.`;
    }
  } else {
    $("submissionStatus").textContent = "Аудио хранится только в этой вкладке.";
  }
}

function renderRecordings() {
  if (!recordings.length) {
    $("recordingsList").innerHTML = '<p class="empty-recording">Записей нет. Проверьте разрешение на использование микрофона и попробуйте ещё раз.</p>';
    return;
  }
  $("recordingsList").innerHTML = recordings.map((item, index) => {
    const extension = item.type.includes("mp4") ? "m4a" : "webm";
    return `<div class="recording-item"><div><b>${item.label}</b><small>Запись ${index + 1}</small></div><a class="download-link" href="${item.url}" download="ege-chinese-${index + 1}.${extension}">Скачать</a><audio controls src="${item.url}"></audio></div>`;
  }).join("");
}

async function exitRun() {
  clearTimer();
  if (recorder?.state === "recording") await stopRecording(`${variant.label} · задание ${taskQueue[taskIndex]} · незавершённая запись`);
  finalizeActiveRun("interrupted");
  phase = "idle";
  activeAssignment = null;
  showScreen("home");
}

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
$("restartBtn").addEventListener("click", () => { activeAssignment = null; showScreen("home"); });
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
$("teacherCabinetBtn").addEventListener("click", async () => { await Promise.all([loadTeacherDashboard(), loadTeacherSubmissions()]); closeModal($("authModal")); openModal($("teacherModal")); });
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
$("soundToggle").addEventListener("click", () => {
  soundEnabled = !soundEnabled;
  $("soundToggle").textContent = soundEnabled ? "Звук включён" : "Звук выключен";
  $("soundToggle").setAttribute("aria-pressed", String(soundEnabled));
  if (soundEnabled) beep();
});

window.addEventListener("beforeunload", () => {
  stream?.getTracks().forEach(track => track.stop());
  recordings.forEach(item => URL.revokeObjectURL(item.url));
});

recoverInterruptedRun();
renderProgress();
setAuthMode("login");

async function initialize() {
  await initVariants();
  await handleAccountLinks();
  await initAuth();
}

initialize();
