import { api } from "../shared/api.js";
import { auditMarkup } from "./account-security.js";
import { progressStorageKeys } from "../shared/progress.js";
import "../shared/site-shell.js";

const $ = id => document.getElementById(id);
let currentUser = null;

async function loadAuditLog() {
  $("auditStatus").textContent = "Загружаем журнал…";
  $("retryAuditBtn").classList.add("hidden");
  try {
    const payload = await api("/api/account/audit");
    $("auditList").innerHTML = auditMarkup(payload.events);
    $("auditStatus").textContent = "Показаны последние события аккаунта.";
  } catch (error) {
    $("auditStatus").textContent = error.message;
    $("retryAuditBtn").classList.remove("hidden");
  }
}

async function loadSecurityPage() {
  try {
    const payload = await api("/api/auth/me");
    currentUser = payload.user;
    $("securityAccountName").textContent = payload.user.displayName;
    $("securityAccountEmail").textContent = payload.user.email;
    $("securityStatus").textContent = "Настройки доступны только владельцу аккаунта.";
    $("securityAccount").classList.remove("hidden");
    await loadAuditLog();
  } catch (error) {
    $("securityStatus").textContent = error.status === 401 ? "Вход не выполнен" : error.message;
    $("securityGuest").classList.remove("hidden");
  }
}

function toggleDeleteAccount() {
  const form = $("deleteAccountForm");
  const expanded = form.classList.contains("hidden");
  form.classList.toggle("hidden", !expanded);
  $("showDeleteAccountBtn").setAttribute("aria-expanded", String(expanded));
  if (expanded) $("deleteAccountPassword").focus();
}

async function deleteAccount(event) {
  event.preventDefault();
  if (!confirm("Удалить аккаунт, прогресс и все связанные аудиозаписи без возможности восстановления?")) return;
  const submit = event.submitter;
  submit.disabled = true;
  $("deleteAccountMessage").textContent = "";
  try {
    await api("/api/account", {
      method: "DELETE",
      body: JSON.stringify({ password: $("deleteAccountPassword").value }),
    });
    const keys = progressStorageKeys(currentUser.id);
    localStorage.removeItem(keys.current);
    localStorage.removeItem(keys.legacy);
    $("securityAccount").classList.add("hidden");
    $("securityDeleted").classList.remove("hidden");
    $("securityStatus").textContent = "Аккаунт и связанные данные удалены.";
    $("securityDeleted").focus();
    document.querySelectorAll("[data-account-link]").forEach(link => {
      link.classList.remove("signed-in");
      link.setAttribute("aria-label", "Войти в личный кабинет");
      const label = link.querySelector("[data-account-label]");
      if (label) label.textContent = "Войти";
    });
  } catch (error) {
    $("deleteAccountMessage").textContent = error.message;
    submit.disabled = false;
  }
}

$("retryAuditBtn").addEventListener("click", loadAuditLog);
$("showDeleteAccountBtn").addEventListener("click", toggleDeleteAccount);
$("deleteAccountForm").addEventListener("submit", deleteAccount);
loadSecurityPage();
