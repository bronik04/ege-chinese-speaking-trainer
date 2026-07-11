import { api } from "../shared/api.js";
import { teacherSubmissionsMarkup } from "./account-view.js";
import { collectReviewScores } from "../runner/review.js";

const $ = (id) => document.getElementById(id);

export function createAccountReviewsController(ctx) {
  const { toast } = ctx;

  function reset() {
    $("teacherSubmissions").innerHTML = "";
    $("reviewQueueCount").textContent = "0 на проверке";
  }

  async function loadTeacherSubmissions() {
    if (ctx.getUser()?.role !== "teacher") return;
    try {
      const params = new URLSearchParams({
        group: $("submissionGroupFilter").value,
        student: $("submissionStudentFilter").value.trim(),
        status: $("submissionStatusFilter").value,
      });
      const payload = await api(`/api/teacher/submissions?${params}`);
      $("teacherSubmissions").innerHTML = teacherSubmissionsMarkup(payload.submissions);
      $("reviewQueueCount").textContent = `${payload.submissions.filter(item => item.status === "submitted").length} на проверке`;
      $("exportCsvBtn").href = `/api/teacher/export.csv?${params}`;
      $("exportPdfBtn").href = `/api/teacher/export.pdf?${params}`;
    } catch (error) {
      $("teacherReviewMessage").textContent = error.message;
    }
  }

  async function showAttemptHistory(event) {
    const button = event.target.closest("[data-attempt-history]");
    if (!button) return;
    const payload = await api(`/api/teacher/submissions/${button.dataset.attemptHistory}`);
    const card = button.closest(".submission-card");
    let panel = card.querySelector(".attempt-history");
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "attempt-history";
      card.append(panel);
    }
    panel.textContent = payload.attempts.map(item => `Попытка ${item.attempt}: ${item.status === "graded" ? `${item.review.total}/${item.review.maximum}` : "на проверке"}`).join(" · ");
  }

  async function submitReview(event) {
    const form = event.target.closest("[data-review-submission]");
    if (!form) return;
    event.preventDefault();
    const tasks = form.dataset.reviewTasks.split(",").map(Number);
    try {
      const payload = await api(`/api/submissions/${form.dataset.reviewSubmission}/review`, {
        method: "POST", body: JSON.stringify({ scores: collectReviewScores(form, tasks), comment: form.elements.comment.value.trim() })
      });
      toast(`Оценка сохранена: ${payload.review.total}/${payload.review.maximum}`);
      await loadTeacherSubmissions();
    } catch (error) {
      $("teacherReviewMessage").textContent = error.message;
    }
  }

  return { reset, loadTeacherSubmissions, showAttemptHistory, submitReview };
}
