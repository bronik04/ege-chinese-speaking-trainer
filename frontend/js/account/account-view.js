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

export function studentReviewRequestsMarkup(requests) {
  if (!requests.length) {
    return '<p class="student-review-requests-empty">Пока нет отправленных разборов.</p>';
  }
  return requests.map(request => {
    const type = request.kind === "attempt" ? "Вся попытка" : "Одно задание";
    const status = request.status === "reviewed"
      ? `Разобрано: ${request.total}/${request.maximum}`
      : request.status === "queued" ? "На разборе" : "Загружаем записи";
    return `<article class="review-request-card"><div><p class="eyebrow">${type}</p><h3>${escapeHtml(request.variantId)}</h3><span>Задания ${request.tasks.join(", ")} · ${formatHistoryDate(request.submittedAt * 1000)}</span><small>${status}</small></div></article>`;
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

export function teacherReviewRequestsMarkup(requests) {
  if (!requests.length) {
    return '<div class="teacher-empty" role="status"><b>Заявок на разбор пока нет</b><span>Когда ученик отправит аудиозапись, она появится здесь.</span></div>';
  }
  return requests.map(request => {
    const type = request.kind === "attempt" ? "Вся попытка" : "Одно задание";
    const scores = Object.fromEntries(request.items.map(item => [item.task, item.scores || {}]));
    const recordings = request.items.flatMap(item => item.recordings || []);
    const status = request.status === "reviewed" ? `${request.total}/${request.maximum}` : "На разборе";
    return `
      <article class="review-request-card teacher-review-request-card">
        <header><div><p class="eyebrow">${type} · ${formatHistoryDate(request.submittedAt * 1000)}</p><h3>${escapeHtml(request.studentName)}</h3><span>${escapeHtml(request.studentEmail)} · Задания ${request.tasks.join(", ")}</span></div><b class="submission-status ${escapeHtml(request.status)}">${status}</b></header>
        <div class="submission-audio">${recordings.length ? recordings.map(recording => `<label><span>${escapeHtml(recording.label)}</span><audio controls preload="none" src="${escapeHtml(recording.url)}"></audio></label>`).join("") : "<p>Аудиозаписи отсутствуют.</p>"}</div>
        <button class="auth-link" type="button" data-student-review-history="${request.id}">История разборов ученика</button>
        <form class="review-form" data-review-request="${request.id}" data-review-tasks="${request.tasks.join(",")}">
          ${reviewFields(request.tasks, scores)}
          <button class="primary-btn" type="submit">${request.status === "reviewed" ? "Обновить оценку" : "Сохранить оценку"}</button>
        </form>
      </article>`;
  }).join("");
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
