import { api, completeReviewRequest, createReviewRequest, uploadReviewRecording } from "../shared/api.js";
import { studentReviewRequestsMarkup } from "./account-view.js";

const $ = (id) => document.getElementById(id);

export function createAccountReviewRequestsController(ctx) {
  let pendingRequest = null;

  function reset() {
    pendingRequest = null;
    $("studentReviewRequestsPanel").classList.add("hidden");
    $("studentReviewRequestsList").innerHTML = "";
  }

  async function loadStudentReviewRequests() {
    if (ctx.getUser()?.role !== "student") {
      $("studentReviewRequestsPanel").classList.add("hidden");
      return;
    }
    try {
      const payload = await api("/api/student/review-requests");
      const requests = payload.requests || [];
      $("studentReviewRequestsPanel").classList.toggle("hidden", !requests.length);
      $("studentReviewRequestsList").innerHTML = studentReviewRequestsMarkup(requests);
    } catch (_) {
      $("studentReviewRequestsPanel").classList.add("hidden");
    }
  }

  function showError(error, selection, runId) {
    const message = $("reviewRequestMessage");
    message.replaceChildren(`Не удалось отправить: ${error.message}. `);
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "secondary-btn";
    retry.textContent = "Повторить отправку";
    retry.addEventListener("click", async () => {
      if (ctx.getCompletedRun()?.id !== runId) {
        message.textContent = "Повторить можно только для исходной попытки.";
        return;
      }
      try {
        await submitReviewRequest(selection);
        ctx.onReviewRequestSent?.();
      } catch (_) {
        // Следующая ошибка заменит это сообщение новой кнопкой повтора.
      }
    });
    message.append(retry);
  }

  async function submitReviewRequest(selection) {
    const tasks = [...new Set(selection.tasks)].sort((left, right) => left - right);
    const run = ctx.getCompletedRun();
    const completedTasks = ctx.getCompletedTasks();
    const recordings = ctx.getCompletedRecordings();
    if (pendingRequest && pendingRequest.runId !== run?.id) pendingRequest = null;
    if (!run || !tasks.length || tasks.some(task => !completedTasks.includes(task))) {
      throw new Error("Выберите завершённое задание");
    }
    if (!recordings.length) throw new Error("Нет аудиозаписей для отправки");
    const sameSelection = pendingRequest
      && pendingRequest.kind === selection.kind
      && pendingRequest.tasks.join(",") === tasks.join(",");
    if (pendingRequest && !sameSelection) {
      throw new Error("Сначала повторите отправку выбранного разбора");
    }
    try {
      if (!pendingRequest) {
        const payload = await createReviewRequest({
          kind: selection.kind,
          tasks,
          variantId: run.variantId,
          run,
        });
        pendingRequest = { id: payload.reviewRequest.id, runId: run.id, kind: selection.kind, tasks };
      }
      for (const recording of recordings.filter(item => tasks.includes(item.task))) {
        await uploadReviewRecording(pendingRequest.id, recording);
      }
      await completeReviewRequest(pendingRequest.id);
      pendingRequest = null;
      $("reviewRequestMessage").textContent = "Заявка отправлена на разбор.";
      ctx.toast("Аудиозаписи отправлены преподавателю");
      await loadStudentReviewRequests();
    } catch (error) {
      showError(error, selection, run.id);
      throw error;
    }
  }

  return {
    reset,
    clearPendingReviewRequest: () => { pendingRequest = null; },
    loadStudentReviewRequests,
    submitReviewRequest,
  };
}
