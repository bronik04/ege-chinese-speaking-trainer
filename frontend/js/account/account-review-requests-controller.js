import {
  api, completeReviewRequest, createReviewRequest, discardReviewRequest, uploadReviewRecording,
} from "../shared/api.js";
import { studentReviewRequestsMarkup } from "./account-view.js";

const $ = (id) => document.getElementById(id);

export function fullyRecordedTasks(tasks, recordings) {
  const positions = new Set(recordings.map(recording => `${recording.task}:${recording.question ?? ""}`));
  return [...new Set(tasks)].sort((left, right) => left - right).filter(task => {
    if (task === 1) return [1, 2, 3, 4, 5].every(question => positions.has(`1:${question}`));
    return [2, 3].includes(task) && positions.has(`${task}:`);
  });
}

export function createAccountReviewRequestsController(ctx) {
  let pendingSubmission = null;

  function reset() {
    pendingSubmission = null;
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

  function showError(error, selection, submission) {
    const message = $("reviewRequestMessage");
    message.replaceChildren(`Не удалось отправить: ${error.message}. `);
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "secondary-btn";
    retry.textContent = "Повторить отправку";
    retry.addEventListener("click", async () => {
      if (pendingSubmission !== submission || ctx.getCompletedRun()?.id !== submission.runId) {
        message.textContent = "Повторить можно только для исходной попытки.";
        return;
      }
      try {
        if (await submitReviewRequest(selection)) ctx.onReviewRequestSent?.();
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
    const recordedTasks = fullyRecordedTasks(completedTasks, recordings);
    if (pendingSubmission && pendingSubmission.runId !== run?.id) pendingSubmission = null;
    if (!run || !tasks.length || tasks.some(task => !recordedTasks.includes(task))) {
      throw new Error("Выберите задание с полным комплектом аудиозаписей");
    }
    const sameSelection = pendingSubmission
      && pendingSubmission.kind === selection.kind
      && pendingSubmission.tasks.join(",") === tasks.join(",");
    if (pendingSubmission && !sameSelection) {
      throw new Error("Сначала повторите отправку выбранного разбора");
    }
    if (pendingSubmission?.running) return pendingSubmission.promise;
    const submission = pendingSubmission || {
      runId: run.id,
      kind: selection.kind,
      tasks,
      requestId: null,
      promise: null,
      running: false,
    };
    pendingSubmission = submission;
    submission.running = true;
    submission.promise = sendReviewRequest(submission, selection, run, recordings);
    return submission.promise;
  }

  async function discardUploadingReviewRequest(requestId) {
    await discardReviewRequest(requestId);
    if (pendingSubmission?.requestId === requestId) pendingSubmission = null;
    ctx.toast("Незавершённая загрузка удалена");
    await loadStudentReviewRequests();
  }

  async function sendReviewRequest(submission, selection, run, recordings) {
    try {
      if (!submission.requestId) {
        const payload = await createReviewRequest({
          kind: selection.kind,
          tasks: submission.tasks,
          variantId: run.variantId,
          run,
        });
        submission.requestId = payload.reviewRequest.id;
      }
      for (const recording of recordings.filter(item => submission.tasks.includes(item.task))) {
        await uploadReviewRecording(submission.requestId, recording);
      }
      await completeReviewRequest(submission.requestId);
      if (pendingSubmission !== submission) return false;
      pendingSubmission = null;
      $("reviewRequestMessage").textContent = "Заявка отправлена на разбор.";
      ctx.toast("Аудиозаписи отправлены преподавателю");
      await loadStudentReviewRequests();
      return true;
    } catch (error) {
      if (pendingSubmission === submission) showError(error, selection, submission);
      throw error;
    } finally {
      submission.running = false;
    }
  }

  return {
    reset,
    clearPendingReviewRequest: () => { pendingSubmission = null; },
    loadStudentReviewRequests,
    submitReviewRequest,
    discardUploadingReviewRequest,
  };
}
