import { api } from "./api.js";
import { mergeProgress } from "./progress.js";

const $ = (id) => document.getElementById(id);

export function createAccountAuthController(ctx) {
  const { toast } = ctx;
  let user = null;
  let mode = "login";
  let syncTimer = null;

  async function initAuth() {
    try {
      const payload = await api("/api/auth/me");
      setUser(payload.user);
      ctx.switchProgressScope(user);
      renderAuth();
    } catch (error) {
      setUser(null);
      ctx.switchProgressScope(null);
      renderAuth();
      if (error.status !== 401) $("progressSyncStatus").textContent = "Сервер недоступен · локальное сохранение";
      return;
    }
    try { await syncProgress(); } catch (_) { $("progressSyncStatus").textContent = "Нет связи · сохранено в браузере"; }
    try { await ctx.refreshAccountData(); } catch (_) {}
  }

  function setUser(value) {
    user = value;
  }

  function renderAuth() {
    const resettingPassword = ctx.isPasswordResetting();
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
    if (!user) ctx.resetAccountViews();
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
      setUser(payload.user);
      ctx.switchProgressScope(user, { adoptGuest: mode === "register" });
      renderAuth();
      try { await syncProgress(); } catch (_) { $("progressSyncStatus").textContent = "Нет связи · сохранено в браузере"; }
      try { await ctx.refreshAccountData(); } catch (_) {}
      closeModal($("authModal"));
      toast(mode === "login" ? "Вход выполнен" : "Аккаунт создан");
      $("authForm").reset();
    } catch (error) {
      $("authMessage").textContent = error.message === "Failed to fetch" ? "Сервер недоступен. Запустите Uvicorn" : error.message;
    } finally {
      $("authSubmitBtn").disabled = false;
    }
  }

  async function logout() {
    try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } catch (_) {}
    clearTimeout(syncTimer);
    setUser(null);
    ctx.switchProgressScope(null);
    renderAuth();
    closeModal($("authModal"));
    toast("Вы вышли из аккаунта. Локальная история сохранена");
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
    setUser,
    initAuth,
    renderAuth,
    setAuthMode,
    openModal,
    closeModal,
    submitAuth,
    logout,
    scheduleProgressSync,
    pushProgress,
    syncProgress,
  };
}
