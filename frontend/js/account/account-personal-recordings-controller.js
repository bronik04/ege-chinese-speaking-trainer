import { listPersonalRecordings, personalRecordingStreamUrl, uploadPersonalRecording } from "../shared/api.js";
import { escapeHtml, formatHistoryDate } from "../shared/progress.js";

const $ = (id) => document.getElementById(id);

export function personalRecordingsMarkup(recordings) {
  if (!recordings.length) return '<p class="history-empty">Сохранённых аудиозаписей пока нет.</p>';
  return recordings.map(recording => {
    const id = Number(recording.id);
    const variant = escapeHtml(recording.variantId || "Вариант");
    const label = escapeHtml(recording.label || "Аудиозапись");
    const position = recording.questionNumber
      ? `задание ${recording.taskNumber}, вопрос ${recording.questionNumber}`
      : `задание ${recording.taskNumber}`;
    return `<article class="personal-recording-item"><div><b>${label}</b><span>${variant} · ${escapeHtml(position)}</span><small>Удалится ${escapeHtml(formatHistoryDate(recording.expiresAt * 1000))}</small></div><audio controls src="${personalRecordingStreamUrl(id)}"></audio></article>`;
  }).join("");
}

export function createAccountPersonalRecordingsController(ctx) {
  const pendingArchives = new Map();

  function reset() {
    pendingArchives.clear();
    $("personalRecordingsList").innerHTML = "";
  }

  async function loadPersonalRecordings() {
    if (ctx.getUser()?.role !== "student") {
      $("personalRecordingsList").innerHTML = "";
      return [];
    }
    const payload = await listPersonalRecordings();
    const recordings = payload.recordings || [];
    $("personalRecordingsList").innerHTML = personalRecordingsMarkup(recordings);
    return recordings;
  }

  function archiveCompletedRun(run, recordings) {
    if (ctx.getUser()?.role !== "student" || !run || !recordings.length) return Promise.resolve();
    if (pendingArchives.has(run.id)) return pendingArchives.get(run.id);
    const archive = (async () => {
      try {
        for (const recording of recordings) {
          try {
            await uploadPersonalRecording(run, recording);
          } catch (error) {
            if (error.code !== "personal_recording_exists") throw error;
          }
        }
        await loadPersonalRecordings();
        ctx.setArchiveStatus("Аудиозаписи сохранены в личном архиве.");
      } catch (_) {
        pendingArchives.delete(run.id);
        ctx.setArchiveStatus("Не удалось сохранить архив. Записи остаются в этой вкладке; попробуйте завершить тренировку позже.");
      }
    })();
    pendingArchives.set(run.id, archive);
    return archive;
  }

  return { archiveCompletedRun, loadPersonalRecordings, reset };
}
