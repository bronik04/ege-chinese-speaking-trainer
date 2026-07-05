import { api } from "./api.js";
import { auditMarkup } from "./account-security.js";
import {
  assignmentOptionsMarkup, studentAssignmentsMarkup, studentGroupsMarkup,
  teacherGroupsMarkup, teacherSubmissionsMarkup,
} from "./account-view.js";
import { escapeHtml, mergeProgress } from "./progress.js";
import { collectReviewScores } from "./review.js";

const $ = (id) => document.getElementById(id);

export function createAccountController(ctx) {
  const { toast } = ctx;
  let user = null;
  let mode = "login";
  let syncTimer = null;
  let studentAssignments = [];
  let teacherGroupsData = [];
  let teacherAssignmentsData = [];
  let passwordResetToken = new URLSearchParams(window.location.search).get("reset");

  async function initAuth() {
    try {
      const payload = await api("/api/auth/me");
      user = payload.user;
      ctx.switchProgressScope(user);
      renderAuth();
    } catch (error) {
      user = null;
      ctx.switchProgressScope(null);
      renderAuth();
      if (error.status !== 401) $("progressSyncStatus").textContent = "Сервер недоступен · локальное сохранение";
      return;
    }
    try { await syncProgress(); } catch (_) { $("progressSyncStatus").textContent = "Нет связи · сохранено в браузере"; }
    try { await refreshAccountData(); } catch (_) {}
  }
  
  function renderAuth() {
    const resettingPassword = Boolean(passwordResetToken);
    $("authButton").classList.toggle("signed-in", Boolean(user));
    $("authButtonText").textContent = user ? user.email : "Войти";
    $("authGuestView").classList.toggle("hidden", Boolean(user) || resettingPassword);
    $("authUserView").classList.toggle("hidden", !user || resettingPassword);
    $("passwordResetView").classList.toggle("hidden", !resettingPassword);
    $("authUserEmail").textContent = user?.email || "";
    $("authUserName").textContent = user?.displayName || "";
    const isTeacher = user?.role === "teacher";
    $("accountRole").textContent = isTeacher ? "Преподаватель" : "Ученик";
    $("accountTitle").textContent = isTeacher ? "Ваши ученики и группы" : "Прогресс синхронизирован";
    $("studentAccountTools").classList.toggle("hidden", !user || isTeacher);
    $("teacherCabinetBtn").classList.toggle("hidden", !isTeacher);
    $("emailVerificationPanel").classList.toggle("hidden", !user || user.emailVerified);
    if (!user) {
      studentAssignments = [];
      teacherGroupsData = [];
      $("studentAssignmentsPanel").classList.add("hidden");
      $("studentAssignmentsList").innerHTML = "";
      $("studentGroups").innerHTML = "";
    }
    ctx.renderProgress();
  }
  
  function setAuthMode(nextMode) {
    mode = nextMode;
    $("loginTab").classList.toggle("active", mode === "login");
    $("registerTab").classList.toggle("active", mode === "register");
    $("authSubmitBtn").textContent = mode === "login" ? "Войти" : "Создать аккаунт";
    $("authPassword").autocomplete = mode === "login" ? "current-password" : "new-password";
    document.querySelectorAll(".register-only").forEach(element => element.classList.toggle("hidden", mode !== "register"));
    $("authName").required = mode === "register";
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
      const payload = await api(`/api/auth/${mode}`, { method: "POST", body: JSON.stringify({ email, password, displayName, role }) });
      user = payload.user;
      ctx.switchProgressScope(user, { adoptGuest: mode === "register" });
      renderAuth();
      try { await syncProgress(); } catch (_) { $("progressSyncStatus").textContent = "Нет связи · сохранено в браузере"; }
      try { await refreshAccountData(); } catch (_) {}
      closeModal($("authModal"));
      toast(mode === "login" ? "Вход выполнен" : "Аккаунт создан");
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
    user = null;
    ctx.switchProgressScope(null);
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
      user = null;
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
      localStorage.removeItem(ctx.getProgressStorageKey());
      user = null;
      ctx.switchProgressScope(null);
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
    if (!user) return;
    if (user.role === "teacher") {
      await Promise.all([loadTeacherDashboard(), loadTeacherSubmissions(), loadTeacherAssignments()]);
    } else {
      await Promise.all([loadStudentGroups(), loadStudentAssignments()]);
    }
  }
  
  async function loadStudentGroups() {
    if (user?.role !== "student") return;
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
    if (user?.role !== "teacher") return;
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
    if (user?.role !== "student") {
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
    await ctx.loadVariant(assignment.variantId);
    if (ctx.getVariant()?.id !== assignment.variantId) {
      toast("Не удалось загрузить вариант задания");
      return;
    }
    $("variantSelect").value = assignment.variantId;
    ctx.startRun(assignment.tasks.length === 3 ? "exam" : String(assignment.tasks[0]), assignment);
  }
  
  function renderAssignmentOptions() {
    const markup = assignmentOptionsMarkup(teacherGroupsData, ctx.getVariantIndex());
    $("assignmentGroup").innerHTML = markup.groups;
    $("assignmentVariant").innerHTML = markup.variants;
    $("createAssignmentBtn").disabled = !teacherGroupsData.length;
    $("submissionGroupFilter").innerHTML = '<option value="">Все группы</option>' + teacherGroupsData.map(group => `<option value="${group.id}">${escapeHtml(group.name)}</option>`).join("");
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
      await loadTeacherAssignments();
    } catch (error) {
      $("teacherMessage").textContent = error.message;
    }
  }
  
  async function loadTeacherSubmissions() {
    if (user?.role !== "teacher") return;
    try {
      const params = new URLSearchParams({ group: $("submissionGroupFilter").value, student: $("submissionStudentFilter").value.trim(), status: $("submissionStatusFilter").value });
      const payload = await api(`/api/teacher/submissions?${params}`);
      renderTeacherSubmissions(payload.submissions);
      $("reviewQueueCount").textContent = `${payload.submissions.filter(item => item.status === "submitted").length} на проверке`;
      $("exportCsvBtn").href = `/api/teacher/export.csv?${params}`;
      $("exportPdfBtn").href = `/api/teacher/export.pdf?${params}`;
    } catch (error) {
      $("teacherReviewMessage").textContent = error.message;
    }
  }
  
  async function loadTeacherAssignments() {
    if (user?.role !== "teacher") return;
    const payload = await api("/api/teacher/assignments");
    teacherAssignmentsData = payload.assignments;
    $("teacherAssignments").innerHTML = teacherAssignmentsData.length ? teacherAssignmentsData.map(item => `
      <article class="teacher-assignment-item"><div><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.groupName)} · ${escapeHtml(item.variantId)} · задания ${item.tasks.join(", ")} · работ ${item.submissionCount}</span></div>
      <div class="teacher-assignment-actions"><button type="button" data-edit-assignment="${item.id}">Изменить</button><button type="button" data-resend-assignment="${item.id}">Выдать повторно</button></div></article>`).join("") : '<p class="teacher-empty">Назначений пока нет.</p>';
  }
  
  async function handleAssignmentAction(event) {
    const editId = Number(event.target.dataset.editAssignment || 0);
    const resendId = Number(event.target.dataset.resendAssignment || 0);
    if (editId) {
      const item = teacherAssignmentsData.find(entry => entry.id === editId);
      const title = prompt("Новое название задания", item.title);
      if (!title) return;
      await api(`/api/teacher/assignments/${editId}`, { method: "PUT", body: JSON.stringify({ title, dueAt: item.dueAt }) });
      toast("Задание обновлено");
    } else if (resendId) {
      if (!confirm("Создать новое назначение на основе этого задания?")) return;
      await api(`/api/teacher/assignments/${resendId}/resend`, { method: "POST", body: "{}" });
      toast("Повторное задание создано");
    } else return;
    await loadTeacherAssignments();
  }
  
  async function showAttemptHistory(event) {
    const button = event.target.closest("[data-attempt-history]");
    if (!button) return;
    const payload = await api(`/api/teacher/submissions/${button.dataset.attemptHistory}`);
    const card = button.closest(".submission-card");
    let panel = card.querySelector(".attempt-history");
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "attempt-history";
      card.append(panel);
    }
    panel.textContent = payload.attempts.map(item => `Попытка ${item.attempt}: ${item.status === "graded" ? `${item.review.total}/${item.review.maximum}` : "на проверке"}`).join(" · ");
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
    if (!user) return;
    await api("/api/progress", { method: "PUT", body: JSON.stringify({ progress: ctx.getProgress() }) });
    $("progressSyncStatus").textContent = `Синхронизировано · ${user.email}`;
  }
  
  async function syncProgress() {
    if (!user) return;
    const payload = await api("/api/progress");
    ctx.setProgress(mergeProgress(ctx.getProgress(), payload.progress));
    ctx.saveProgressLocal(false);
    await pushProgress();
  }
  
  

  return {
    get user() { return user; },
    initAuth, renderAuth, setAuthMode, openModal, closeModal, submitAuth, logout,
    requestPasswordReset, submitPasswordReset, cancelPasswordReset,
    sendVerificationEmail, loadAuditLog, deleteAccount, handleAccountLinks,
    refreshAccountData, loadStudentGroups, joinGroup, loadTeacherDashboard,
    loadStudentAssignments, startAssignedRun, renderAssignmentOptions,
    createAssignment, loadTeacherSubmissions, loadTeacherAssignments,
    handleAssignmentAction, showAttemptHistory, submitReview, createGroup,
    scheduleProgressSync, pushProgress, syncProgress,
  };
}
