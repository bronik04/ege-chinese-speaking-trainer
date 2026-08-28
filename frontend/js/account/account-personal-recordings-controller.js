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
  const archives = new Map();

  function reset() {
    archives.clear();
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

  async function syncArchive(archive) {
    if (archive.promise) return archive.promise;
    archive.promise = (async () => {
      try {
        for (const recording of [...archive.pending]) {
          try {
            await uploadPersonalRecording(archive.run, recording);
            archive.pending = archive.pending.filter(item => item !== recording);
          } catch (error) {
            if (error.code === "personal_recording_exists") archive.pending = archive.pending.filter(item => item !== recording);
            else throw error;
          }
        }
        await loadPersonalRecordings();
        archives.delete(archive.run.id);
        ctx.setArchiveStatus("Аудиозаписи сохранены в личном архиве.", false);
      } catch (_) {
        ctx.setArchiveStatus("Не удалось сохранить архив. Записи остаются в этой вкладке.", true);
      } finally {
        archive.promise = null;
      }
    })();
    return archive.promise;
  }

  function archiveCompletedRun(run, recordings) {
    if (ctx.getUser()?.role !== "student" || !run || !recordings.length) return Promise.resolve();
    let archive = archives.get(run.id);
    if (!archive) {
      archive = { run, pending: [...recordings], promise: null };
      archives.set(run.id, archive);
    }
    return syncArchive(archive);
  }

  function retryArchive(run) {
    const archive = archives.get(run?.id);
    return archive ? syncArchive(archive) : Promise.resolve();
  }

  return { archiveCompletedRun, retryArchive, loadPersonalRecordings, reset };
}
