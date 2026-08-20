import { api } from "../shared/api.js";
import { teacherReviewRequestsMarkup } from "./account-view.js";
import { collectReviewScores } from "../runner/review.js";
import { pluralize } from "../shared/plural.js";
import { formatHistoryDate } from "../shared/progress.js";

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
    let panel = card.querySelector(".attempt-history");
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "attempt-history";
      card.append(panel);
    }
    const history = (historyPayload.requests || []).filter(item => item.studentId === request.studentId);
    panel.textContent = history.length
      ? history.map(item => `${formatHistoryDate(item.submittedAt * 1000)}: ${item.status === "reviewed" ? `${item.total}/${item.maximum}` : "на разборе"}`).join(" · ")
      : "Других заявок ученика пока нет.";
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
