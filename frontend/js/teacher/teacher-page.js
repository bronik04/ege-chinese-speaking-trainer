import { createAccountReviewsController } from "../account/account-reviews-controller.js";
import { api } from "../shared/api.js";

const $ = (id) => document.getElementById(id);
let toastTimer;

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("toast").classList.add("hidden"), 2200);
}

function redirectToAccount() {
  window.location.replace("index.html?account=1");
}

function selectedRequestId() {
  const value = Number(new URL(window.location.href).searchParams.get("request"));
  return Number.isInteger(value) && value > 0 ? value : null;
}

function rememberRequest(requestId) {
  const url = new URL(window.location.href);
  url.searchParams.set("request", String(requestId));
  window.history.replaceState({}, "", url);
}

function forgetRequest() {
  const url = new URL(window.location.href);
  url.searchParams.delete("request");
  window.history.replaceState({}, "", url);
}

async function showRequestHistory(reviews, requestId, { updateUrl = false } = {}) {
  try {
    await reviews.showStudentReviewHistory(requestId);
    $("teacherReviewMessage").textContent = "";
    if (updateUrl) rememberRequest(requestId);
  } catch (error) {
    $("teacherReviewMessage").textContent = error.message;
    forgetRequest();
  }
}

async function initialize() {
  let user;
  try {
    user = (await api("/api/auth/me")).user;
  } catch (error) {
    if (error.status === 401) return redirectToAccount();
    $("teacherAccessMessage").textContent = error.message;
    return;
  }
  if (user.role !== "teacher") return redirectToAccount();

  $("teacherAccessMessage").textContent = `${user.displayName} · преподаватель`;
  $("teacherWorkspace").classList.remove("hidden");
  const accountLink = document.querySelector("[data-account-link]");
  accountLink?.classList.add("signed-in");
  const label = accountLink?.querySelector("[data-account-label]");
  if (label) label.textContent = user.displayName;

  const reviews = createAccountReviewsController({ toast, getUser: () => user });
  $("reviewRequestFilters").addEventListener("submit", event => {
    event.preventDefault();
    reviews.loadTeacherReviewRequests();
  });
  $("teacherReviewRequests").addEventListener("submit", event => {
    const form = event.target.closest("[data-review-request]");
    if (!form) return;
    event.preventDefault();
    reviews.saveReviewScores(form);
  });
  $("teacherReviewRequests").addEventListener("click", async event => {
    const button = event.target.closest("[data-student-review-history]");
    if (!button) return;
    const requestId = Number(button.dataset.studentReviewHistory);
    await showRequestHistory(reviews, requestId, { updateUrl: true });
  });
  await reviews.loadTeacherReviewRequests();
  const requestId = selectedRequestId();
  if (requestId) await showRequestHistory(reviews, requestId);
}

initialize();
