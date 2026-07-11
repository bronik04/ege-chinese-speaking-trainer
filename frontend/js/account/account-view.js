import { escapeHtml, formatHistoryDate } from "../shared/progress.js";
import { reviewFields } from "../runner/review.js";

export function studentGroupsMarkup(groups) {
  if (!groups.length) return '<p class="student-groups-empty">Вы пока не состоите в учебной группе.</p>';
  return `<p class="mini-heading">Мои группы</p>${groups.map(group =>
    `<div class="student-group"><b>${escapeHtml(group.name)}</b><span>${escapeHtml(group.teacher_name || "Преподаватель")}</span></div>`
  ).join("")}`;
}

export function studentAssignmentsMarkup(assignments) {
  return assignments.map(assignment => {
    const latest = assignment.latest;
    const status = latest?.late
      ? "Сдано после срока"
      : latest?.status === "graded"
      ? `Проверено: ${latest.total_score}/${latest.max_score}`
      : latest ? "Отправлено на проверку" : "Не выполнено";
    const due = assignment.dueAt ? ` · до ${formatHistoryDate(assignment.dueAt * 1000)}` : "";
    return `<article class="assignment-card"><div><p class="eyebrow">${escapeHtml(assignment.groupName)}</p><h3>${escapeHtml(assignment.title)}</h3><span>Задания ${assignment.tasks.join(", ")}${due}</span><small>${status}</small>${latest?.comment ? `<blockquote>${escapeHtml(latest.comment)}</blockquote>` : ""}</div><button class="secondary-btn" type="button" data-start-assignment="${assignment.id}">${latest ? "Новая попытка" : "Начать"}</button></article>`;
  }).join("");
}

export function assignmentTasksMarkup(variant) {
  if (variant?.kind === "task") {
    return `<option value="${variant.taskNumber}">Только задание ${variant.taskNumber}</option>`;
  }
  return '<option value="exam">Полный экзамен</option><option value="1">Только задание 1</option><option value="2">Только задание 2</option><option value="3">Только задание 3</option>';
}

export function assignmentOptionsMarkup(groups, variants) {
  return {
    groups: groups.length
      ? groups.map(group => `<option value="${group.id}">${escapeHtml(group.name)}</option>`).join("")
      : '<option value="">Сначала создайте группу</option>',
    variants: variants.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join(""),
  };
}

export function teacherSubmissionsMarkup(submissions) {
  if (!submissions.length) {
    return '<div class="teacher-empty"><b>Работ на проверку пока нет</b><span>После выполнения назначений здесь появятся аудиозаписи учеников.</span></div>';
  }
  return submissions.map(submission => `
    <article class="submission-card">
      <header><div><p class="eyebrow">${escapeHtml(submission.groupName)} · попытка ${submission.attempt}</p><h3>${escapeHtml(submission.studentName)}</h3><span>${escapeHtml(submission.title)}${submission.late ? " · Сдано после срока" : ""}</span></div><b class="submission-status ${escapeHtml(submission.status)}">${submission.status === "graded" ? `${submission.review.total}/${submission.review.maximum}` : "На проверке"}</b></header>
      <div class="submission-audio">${submission.recordings.length ? submission.recordings.map(recording => `<label><span>${escapeHtml(recording.label)}</span><audio controls preload="none" src="${escapeHtml(recording.url)}"></audio>${transcriptMarkup(recording)}</label>`).join("") : "<p>Аудиозаписи отсутствуют.</p>"}</div>
      <button class="auth-link" type="button" data-attempt-history="${submission.id}">История попыток</button>
      <form class="review-form" data-review-submission="${submission.id}" data-review-tasks="${submission.tasks.join(",")}">
        ${reviewFields(submission.tasks, submission.review?.scores)}
        <label class="review-comment">Комментарий<textarea name="comment" maxlength="3000" rows="3">${escapeHtml(submission.review?.comment || "")}</textarea></label>
        <button class="primary-btn" type="submit">${submission.review ? "Обновить оценку" : "Сохранить оценку"}</button>
      </form>
    </article>`).join("");
}

function transcriptMarkup(recording) {
  if (recording.transcript_status === "completed") {
    return `<details class="recording-transcript"><summary>Расшифровка</summary><p>${escapeHtml(recording.transcript_text || "")}</p></details>`;
  }
  if (recording.transcript_status === "pending" || recording.transcript_status === "processing") {
    return '<small class="transcript-status">Расшифровка готовится…</small>';
  }
  if (recording.transcript_status === "failed") {
    return '<small class="transcript-status error">Не удалось расшифровать запись</small>';
  }
  return "";
}

export function teacherGroupsMarkup(groups) {
  if (!groups.length) {
    return '<div class="teacher-empty"><b>Групп пока нет</b><span>Создайте первую группу — здесь появится статистика учеников.</span></div>';
  }
  return groups.map(group => `
    <article class="teacher-group-card">
      <header><div><h3>${escapeHtml(group.name)}</h3><span>${group.students.length} ${group.students.length === 1 ? "ученик" : "учеников"}</span></div><button class="group-code" type="button" data-copy-code="${escapeHtml(group.code)}" title="Скопировать код"><small>Код группы</small><b>${escapeHtml(group.code)}</b></button></header>
      ${group.students.length ? `<div class="student-table"><div class="student-table-head"><span>Ученик</span><span>Тренировки</span><span>Задания</span><span>Последняя активность</span></div>${group.students.map(student => `<div class="student-row"><span><b>${escapeHtml(student.name)}</b><small>${escapeHtml(student.email)}</small></span><strong>${student.completedRuns}</strong><strong>${student.completedTasks}</strong><time>${student.lastActivity ? formatHistoryDate(student.lastActivity) : "—"}</time></div>`).join("")}</div>` : '<p class="group-empty">Передайте код ученикам — после подключения они появятся здесь.</p>'}
    </article>`).join("");
}
