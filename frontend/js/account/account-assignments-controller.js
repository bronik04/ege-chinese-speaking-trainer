import { api } from "../shared/api.js";
import { assignmentOptionsMarkup, assignmentTasksMarkup, studentAssignmentsMarkup } from "./account-view.js";
import { escapeHtml } from "../shared/progress.js";

const $ = (id) => document.getElementById(id);

export function createAccountAssignmentsController(ctx) {
  const { toast } = ctx;
  let studentAssignments = [];
  let teacherAssignments = [];

  function reset() {
    studentAssignments = [];
    teacherAssignments = [];
    $("studentAssignmentsPanel").classList.add("hidden");
    $("studentAssignmentsList").innerHTML = "";
    $("teacherAssignments").innerHTML = "";
  }

  async function loadStudentAssignments() {
    if (ctx.getUser()?.role !== "student") {
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
    await ctx.loadVariant(assignment.variantId, assignment.material);
    if (ctx.getVariant()?.id !== assignment.variantId) {
      toast("Не удалось загрузить вариант задания");
      return;
    }
    $("variantSelect").value = assignment.variantId;
    ctx.startRun(assignment.tasks.length === 3 ? "exam" : String(assignment.tasks[0]), assignment);
  }

  function renderAssignmentOptions() {
    const groups = ctx.getTeacherGroups();
    const markup = assignmentOptionsMarkup(groups, ctx.getVariantIndex());
    $("assignmentGroup").innerHTML = markup.groups;
    $("assignmentVariant").innerHTML = markup.variants;
    const updateTasks = () => {
      const selected = ctx.getVariantIndex().find(item => item.id === $("assignmentVariant").value);
      $("assignmentTasks").innerHTML = assignmentTasksMarkup(selected);
    };
    $("assignmentVariant").onchange = updateTasks;
    updateTasks();
    $("createAssignmentBtn").disabled = !groups.length;
    $("submissionGroupFilter").innerHTML = '<option value="">Все группы</option>' + groups.map(group => `<option value="${group.id}">${escapeHtml(group.name)}</option>`).join("");
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

  async function loadTeacherAssignments() {
    if (ctx.getUser()?.role !== "teacher") return;
    try {
      const payload = await api("/api/teacher/assignments");
      teacherAssignments = payload.assignments;
      $("teacherAssignments").innerHTML = teacherAssignments.length ? teacherAssignments.map(item => `
        <article class="teacher-assignment-item"><div><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.groupName)} · ${escapeHtml(item.variantId)} · задания ${item.tasks.join(", ")} · работ ${item.submissionCount}</span></div>
        <div class="teacher-assignment-actions"><button type="button" data-edit-assignment="${item.id}">Изменить</button><button type="button" data-resend-assignment="${item.id}">Выдать повторно</button></div></article>`).join("") : '<p class="teacher-empty">Назначений пока нет.</p>';
    } catch (error) {
      $("teacherMessage").textContent = error.message;
    }
  }

  async function handleAssignmentAction(event) {
    const editId = Number(event.target.dataset.editAssignment || 0);
    const resendId = Number(event.target.dataset.resendAssignment || 0);
    if (editId) {
      const item = teacherAssignments.find(entry => entry.id === editId);
      if (!item) return;
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

  return {
    reset,
    loadStudentAssignments,
    startAssignedRun,
    renderAssignmentOptions,
    createAssignment,
    loadTeacherAssignments,
    handleAssignmentAction,
  };
}
