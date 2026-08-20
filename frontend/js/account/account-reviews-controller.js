import { api } from "../shared/api.js";
import { teacherReviewRequestDetailMarkup, teacherReviewRequestsMarkup } from "./account-view.js";
import { collectReviewScores } from "../runner/review.js";
import { pluralize } from "../shared/plural.js";

const $ = (id) => document.getElementById(id);

export function createAccountReviewsController(ctx) {
  const { toast } = ctx;
  let requests = [];

  function reset() {
    requests = [];
    $("teacherReviewRequests").innerHTML = "";
    $("reviewQueueCount").textContent = "Нет заявок на разбор";
  }

  async function loadTeacherReviewRequests() {
    if (ctx.getUser()?.role !== "teacher") return;
    try {
      const params = new URLSearchParams({
        student: $("reviewStudentFilter").value.trim(),
        task: $("reviewTaskFilter").value,
        status: $("reviewStatusFilter").value,
      });
      const selectedDate = $("reviewDateFilter").value;
      if (selectedDate) {
        const submittedFrom = new Date(`${selectedDate}T00:00:00`);
        const submittedBefore = new Date(submittedFrom);
        submittedBefore.setDate(submittedBefore.getDate() + 1);
        params.set("submittedFrom", String(Math.floor(submittedFrom.getTime() / 1000)));
        params.set("submittedBefore", String(Math.floor(submittedBefore.getTime() / 1000)));
      }
      const payload = await api(`/api/teacher/review-requests?${params}`);
      requests = payload.requests || [];
      $("teacherReviewRequests").innerHTML = teacherReviewRequestsMarkup(requests);
      const queue = requests.filter(item => item.status === "queued").length;
      $("reviewQueueCount").textContent = queue
        ? `${pluralize(queue, "заявка", "заявки", "заявок")} на разборе`
        : "Нет заявок на разбор";
    } catch (error) {
      $("teacherReviewMessage").textContent = error.message;
    }
  }

  async function showStudentReviewHistory(requestId) {
    const payload = await api(`/api/teacher/review-requests/${requestId}`);
    const request = payload.reviewRequest;
    const historyPayload = await api(`/api/teacher/review-requests?${new URLSearchParams({ student: request.studentEmail })}`);
    const card = document.querySelector(`[data-student-review-history="${requestId}"]`)?.closest(".teacher-review-request-card");
    if (!card) return;
    let panel = card.querySelector(".review-request-detail");
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "review-request-detail";
      card.append(panel);
    }
    const history = (historyPayload.requests || []).filter(item => item.studentId === request.studentId);
    panel.innerHTML = teacherReviewRequestDetailMarkup(request, history);
  }

  async function saveReviewScores(form) {
    const tasks = form.dataset.reviewTasks.split(",").map(Number);
    try {
      const payload = await api(`/api/teacher/review-requests/${form.dataset.reviewRequest}/scores`, {
        method: "PUT", body: JSON.stringify({ scores: collectReviewScores(form, tasks) })
      });
      toast(`Оценка сохранена: ${payload.reviewRequest.total}/${payload.reviewRequest.maximum}`);
      await loadTeacherReviewRequests();
    } catch (error) {
      $("teacherReviewMessage").textContent = error.message;
    }
  }

  return { reset, loadTeacherReviewRequests, showStudentReviewHistory, saveReviewScores };
}
