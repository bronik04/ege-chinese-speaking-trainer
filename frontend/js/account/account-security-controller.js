import { api } from "../shared/api.js";
import { auditMarkup } from "./account-security.js";

const $ = (id) => document.getElementById(id);

export function createAccountSecurityController(ctx) {
  const { auth, toast } = ctx;
  let passwordResetToken = new URLSearchParams(window.location.search).get("reset");

  function isPasswordResetting() {
    return Boolean(passwordResetToken);
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
      auth.setUser(null);
      auth.renderAuth();
      auth.setAuthMode("login");
      $("authMessage").textContent = "Пароль изменён. Войдите с новым паролем.";
    } catch (error) {
      $("passwordResetMessage").textContent = error.message;
    }
  }

  function cancelPasswordReset() {
    passwordResetToken = null;
    window.history.replaceState({}, "", window.location.pathname);
    auth.renderAuth();
    auth.setAuthMode("login");
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
      auth.setUser(null);
      ctx.switchProgressScope(null);
      auth.renderAuth();
      auth.closeModal($("authModal"));
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
      auth.renderAuth();
      auth.openModal($("authModal"));
    }
  }

  return {
    isPasswordResetting,
    requestPasswordReset,
    submitPasswordReset,
    cancelPasswordReset,
    sendVerificationEmail,
    loadAuditLog,
    deleteAccount,
    handleAccountLinks,
  };
}
