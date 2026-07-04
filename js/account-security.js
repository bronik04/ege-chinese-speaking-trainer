import { escapeHtml, formatHistoryDate } from "./progress.js";

export const AUDIT_LABELS = {
  account_registered: "Аккаунт создан",
  login_succeeded: "Выполнен вход",
  login_failed: "Неудачная попытка входа",
  logout: "Выполнен выход",
  email_verification_requested: "Запрошено подтверждение email",
  email_verified: "Email подтверждён",
  password_reset_requested: "Запрошено восстановление пароля",
  password_reset_completed: "Пароль изменён",
  account_deletion_failed: "Неудачная попытка удаления аккаунта",
  group_created: "Создана учебная группа",
  group_joined: "Вступление в учебную группу",
  assignment_created: "Создано назначение",
  submission_created: "Работа отправлена",
  recording_uploaded: "Аудиозапись загружена",
  submission_reviewed: "Работа проверена",
};

export function auditMarkup(events) {
  if (!events.length) return '<p class="student-groups-empty">Событий пока нет.</p>';
  return events.map(event => `
    <article class="audit-item">
      <b>${escapeHtml(AUDIT_LABELS[event.action] || event.action)}</b>
      <span>${escapeHtml(formatHistoryDate(event.createdAt * 1000))} · IP ${escapeHtml(event.ipAddress || "—")}</span>
    </article>`).join("");
}
