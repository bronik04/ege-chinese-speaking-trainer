import { uploadPersonalRecording } from "../shared/api.js";

export function createAccountPersonalRecordingsController(ctx) {
  const archives = new Map();
  let generation = 0;

  const isCurrent = archive => (
    archive.generation === generation && ctx.getUser()?.id === archive.ownerId
  );

  function reset() {
    generation += 1;
    archives.clear();
  }

  async function syncArchive(archive) {
    if (archive.promise) return archive.promise;
    archive.promise = (async () => {
      try {
        for (const recording of [...archive.pending]) {
          if (!isCurrent(archive)) return false;
          try {
            await uploadPersonalRecording(archive.run, recording);
            if (!isCurrent(archive)) return false;
            archive.pending = archive.pending.filter(item => item !== recording);
          } catch (error) {
            if (error.code === "personal_recording_exists") archive.pending = archive.pending.filter(item => item !== recording);
            else throw error;
          }
        }
        if (!isCurrent(archive)) return false;
        archives.delete(archive.run.id);
        return true;
      } catch (_) {
        return false;
      } finally {
        archive.promise = null;
      }
    })();
    return archive.promise;
  }

  function archiveCompletedRun(run, recordings) {
    const owner = ctx.getUser();
    if (owner?.role !== "student" || !run || !recordings.length) return Promise.resolve();
    let archive = archives.get(run.id);
    if (!archive) {
      archive = { run, pending: [...recordings], promise: null, ownerId: owner.id, generation };
      archives.set(run.id, archive);
    }
    return retryArchive();
  }

  async function retryArchive() {
    const ownerId = ctx.getUser()?.id;
    const retryGeneration = generation;
    const pending = [...archives.values()].filter(isCurrent);
    for (const archive of pending) await syncArchive(archive);
    if (generation !== retryGeneration || ctx.getUser()?.id !== ownerId) return;
    const hasPending = [...archives.values()].some(isCurrent);
    ctx.setArchiveStatus(
      hasPending ? "Не удалось сохранить архив. Записи остаются в этой вкладке." : "Аудиозаписи сохранены в личном архиве.",
      hasPending,
    );
  }

  return { archiveCompletedRun, retryArchive, reset };
}
