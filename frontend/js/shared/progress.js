export const PROGRESS_GUEST_KEY = "egeChineseProgressV1";
export const PROGRESS_ACCOUNT_PREFIX = `${PROGRESS_GUEST_KEY}:user:`;

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
}

export function defaultProgress() {
  return { version: 1, updatedAt: new Date(0).toISOString(), settings: { lastVariant: null, fastMode: false }, runs: [], activeRun: null };
}

export function loadLocalProgress(storageKey) {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey));
    if (saved?.version === 1 && Array.isArray(saved.runs)) {
      return { ...defaultProgress(), ...saved, settings: { ...defaultProgress().settings, ...saved.settings } };
    }
  } catch (_) {}
  return defaultProgress();
}

export function mergeProgress(local, remote) {
  if (!remote || remote.version !== 1) return local;
  const runs = new Map();
  [...(remote.runs || []), ...(local.runs || [])].forEach(run => { if (run?.id) runs.set(run.id, run); });
  const localIsNewer = new Date(local.updatedAt || 0) >= new Date(remote.updatedAt || 0);
  return {
    version: 1,
    updatedAt: new Date().toISOString(),
    settings: localIsNewer ? local.settings : remote.settings,
    runs: [...runs.values()].sort((a, b) => new Date(b.completedAt || b.startedAt) - new Date(a.completedAt || a.startedAt)).slice(0, 100),
    activeRun: local.activeRun || null
  };
}

export function formatHistoryDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function createRunId() {
  return crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
