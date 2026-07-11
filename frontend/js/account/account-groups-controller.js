import { api } from "../shared/api.js";
import { studentGroupsMarkup, teacherGroupsMarkup } from "./account-view.js";

const $ = (id) => document.getElementById(id);

export function createAccountGroupsController(ctx) {
  const { toast } = ctx;
  let teacherGroups = [];

  function reset() {
    teacherGroups = [];
    $("studentGroups").innerHTML = "";
    $("teacherGroups").innerHTML = "";
  }

  function getTeacherGroups() {
    return teacherGroups;
  }

  async function loadStudentGroups() {
    if (ctx.getUser()?.role !== "student") return;
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
      await Promise.all([loadStudentGroups(), ctx.loadStudentAssignments()]);
      toast(`Вы вступили в группу «${payload.group.name}»`);
    } catch (error) {
      toast(error.message);
    }
  }

  async function loadTeacherDashboard() {
    if (ctx.getUser()?.role !== "teacher") return;
    try {
      const payload = await api("/api/teacher/dashboard");
      teacherGroups = payload.groups;
      renderTeacherGroups(teacherGroups);
      ctx.onTeacherGroupsChanged();
    } catch (error) {
      $("teacherMessage").textContent = error.message;
    }
  }

  function renderTeacherGroups(groups) {
    $("teacherGroups").innerHTML = teacherGroupsMarkup(groups);
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

  return { reset, getTeacherGroups, loadStudentGroups, joinGroup, loadTeacherDashboard, createGroup };
}
