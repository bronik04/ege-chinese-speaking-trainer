export const PROGRESS_GUEST_KEY = "egeChineseProgressV2";
export const PROGRESS_ACCOUNT_PREFIX = `${PROGRESS_GUEST_KEY}:user:`;
export const LEGACY_PROGRESS_GUEST_KEY = "egeChineseProgressV1";
export const LEGACY_PROGRESS_ACCOUNT_PREFIX = `${LEGACY_PROGRESS_GUEST_KEY}:user:`;

const ROOT_FIELDS = ["version", "updatedAt", "settings", "runs", "activeRun"];
const SETTINGS_FIELDS = ["lastVariant", "fastMode"];
const RUN_FIELDS = [
  "id", "variantId", "variantLabel", "mode", "tasks", "completedTasks",
  "currentTask", "phase", "fastMode", "startedAt",
];
const COMPLETED_FIELDS = [...RUN_FIELDS, "status", "completedAt", "recordingsCount"];
const RFC3339 = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|([+-])(\d{2}):(\d{2}))$/;
const EPOCH = "1970-01-01T00:00:00.000Z";

export class ProgressContractError extends Error {
  constructor(reason = "invalid_document") {
    super(reason);
    this.name = "ProgressContractError";
    this.reason = reason;
  }
}

function invalid(reason = "invalid_document") {
  throw new ProgressContractError(reason);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && Object.getPrototypeOf(value) === Object.prototype;
}

function exactObject(value, fields) {
  if (!isObject(value)) invalid();
  const keys = Object.keys(value);
  if (keys.length !== fields.length || keys.some(key => !fields.includes(key))) invalid();
  return value;
}

function stringValue(value, minimum, maximum) {
  if (typeof value !== "string" || value.length < minimum || value.length > maximum) invalid();
  return value;
}

function booleanValue(value) {
  if (typeof value !== "boolean") invalid();
  return value;
}

function integerValue(value, minimum, maximum) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) invalid();
  return value;
}

function timestamp(value) {
  if (typeof value !== "string") invalid();
  const match = RFC3339.exec(value);
  if (!match) invalid();
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, fraction = "", zone] = match;
  const [year, month, day, hour, minute, second] = [
    yearText, monthText, dayText, hourText, minuteText, secondText,
  ].map(Number);
  if (year < 1 || month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) invalid();
  const milliseconds = Number(fraction.padEnd(3, "0").slice(0, 3));
  const calendar = new Date(0);
  calendar.setUTCFullYear(year, month - 1, day);
  calendar.setUTCHours(hour, minute, second, milliseconds);
  if (calendar.getUTCFullYear() !== year || calendar.getUTCMonth() !== month - 1 || calendar.getUTCDate() !== day) {
    invalid();
  }
  let offsetMinutes = 0;
  if (zone !== "Z") {
    const offsetHours = Number(match[10]);
    const offsetMinutePart = Number(match[11]);
    if (offsetHours > 23 || offsetMinutePart > 59) invalid();
    offsetMinutes = (offsetHours * 60 + offsetMinutePart) * (match[9] === "+" ? 1 : -1);
  }
  const utc = new Date(calendar.getTime() - offsetMinutes * 60_000);
  if (utc.getUTCFullYear() < 1 || utc.getUTCFullYear() > 9999) invalid();
  return utc.toISOString();
}

function choice(value, allowed) {
  if (typeof value !== "string" || !allowed.includes(value)) invalid();
  return value;
}

function task(value) {
  return integerValue(value, 1, 3);
}

function tasks(value, { allowEmpty }) {
  if (!Array.isArray(value) || value.length > 3 || (!allowEmpty && value.length === 0)) invalid();
  const result = value.map(task);
  if (new Set(result).size !== result.length) invalid();
  return result.toSorted((left, right) => left - right);
}

function parseRunFields(value, fields) {
  const source = exactObject(value, fields);
  const runTasks = tasks(source.tasks, { allowEmpty: false });
  const completedTasks = tasks(source.completedTasks, { allowEmpty: true });
  const mode = choice(source.mode, ["exam", "practice"]);
  if ((mode === "exam" && runTasks.join() !== "1,2,3") || (mode === "practice" && runTasks.length !== 1)) {
    invalid();
  }
  if (completedTasks.some(item => !runTasks.includes(item))) invalid();
  const currentTask = task(source.currentTask);
  if (!runTasks.includes(currentTask)) invalid();
  const startedAt = timestamp(source.startedAt);
  return {
    run: {
      id: stringValue(source.id, 1, 120),
      variantId: stringValue(source.variantId, 1, 80),
      variantLabel: stringValue(source.variantLabel, 1, 160),
      mode,
      tasks: runTasks,
      completedTasks,
      currentTask,
      phase: choice(source.phase, ["idle", "prep", "answer"]),
      fastMode: booleanValue(source.fastMode),
      startedAt,
    },
    started: new Date(startedAt).getTime(),
  };
}

function parseActiveRun(value) {
  return parseRunFields(value, RUN_FIELDS).run;
}

function parseCompletedRun(value) {
  const { run, started } = parseRunFields(value, COMPLETED_FIELDS);
  const status = choice(value.status, ["completed", "interrupted"]);
  const completedAt = timestamp(value.completedAt);
  if (new Date(completedAt).getTime() < started) invalid();
  if (status === "completed" && run.completedTasks.join() !== run.tasks.join()) invalid();
  return {
    ...run,
    status,
    completedAt,
    recordingsCount: integerValue(value.recordingsCount, 0, 100),
  };
}

function parseSettings(value) {
  const source = exactObject(value, SETTINGS_FIELDS);
  return {
    lastVariant: source.lastVariant === null ? null : stringValue(source.lastVariant, 1, 80),
    fastMode: booleanValue(source.fastMode),
  };
}

function parseV2(value) {
  const source = exactObject(value, ROOT_FIELDS);
  if (!Number.isInteger(source.version) || source.version !== 2) invalid();
  if (!Array.isArray(source.runs) || source.runs.length > 100) invalid();
  const runs = source.runs.map(parseCompletedRun);
  if (new Set(runs.map(run => run.id)).size !== runs.length) invalid();
  return {
    version: 2,
    updatedAt: timestamp(source.updatedAt),
    settings: parseSettings(source.settings),
    runs,
    activeRun: source.activeRun === null ? null : parseActiveRun(source.activeRun),
  };
}

function knownFields(value, fields) {
  if (!isObject(value)) invalid();
  return Object.fromEntries(fields.filter(field => Object.hasOwn(value, field)).map(field => [field, value[field]]));
}

function legacyTimestamp(value) {
  try {
    return timestamp(value);
  } catch (error) {
    if (!(error instanceof ProgressContractError)) throw error;
    return EPOCH;
  }
}

function legacySettings(value) {
  const source = isObject(value) ? value : {};
  const lastVariant = typeof source.lastVariant === "string"
    && source.lastVariant.length >= 1 && source.lastVariant.length <= 80
    ? source.lastVariant
    : null;
  return {
    lastVariant,
    fastMode: typeof source.fastMode === "boolean" ? source.fastMode : false,
  };
}

function migrateV1(source) {
  const rawRuns = Object.hasOwn(source, "runs") ? source.runs : [];
  if (!Array.isArray(rawRuns)) invalid();
  if (rawRuns.length > 200) invalid("history_too_large");
  const runs = [];
  const seen = new Set();
  for (const value of rawRuns) {
    try {
      const run = parseCompletedRun(knownFields(value, COMPLETED_FIELDS));
      if (seen.has(run.id)) continue;
      seen.add(run.id);
      runs.push(run);
      if (runs.length === 100) break;
    } catch (error) {
      if (!(error instanceof ProgressContractError)) throw error;
    }
  }
  let activeRun = null;
  if (source.activeRun != null) {
    try {
      activeRun = parseActiveRun(knownFields(source.activeRun, RUN_FIELDS));
    } catch (error) {
      if (!(error instanceof ProgressContractError)) throw error;
    }
  }
  return parseV2({
    version: 2,
    updatedAt: legacyTimestamp(source.updatedAt ?? EPOCH),
    settings: legacySettings(source.settings),
    runs,
    activeRun,
  });
}

export function normalizeProgress(value) {
  if (!isObject(value) || !Number.isInteger(value.version)) invalid();
  if (value.version === 1) return migrateV1(value);
  if (value.version === 2) return parseV2(value);
  return invalid();
}

export function progressStorageKeys(userId = null) {
  return userId == null
    ? { current: PROGRESS_GUEST_KEY, legacy: LEGACY_PROGRESS_GUEST_KEY }
    : { current: `${PROGRESS_ACCOUNT_PREFIX}${userId}`, legacy: `${LEGACY_PROGRESS_ACCOUNT_PREFIX}${userId}` };
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
}

export function defaultProgress() {
  return { version: 2, updatedAt: EPOCH, settings: { lastVariant: null, fastMode: false }, runs: [], activeRun: null };
}

export function loadLocalProgress(keys, { storage = localStorage, onError = () => {} } = {}) {
  const currentRaw = storage.getItem(keys.current);
  if (currentRaw !== null) {
    try {
      return normalizeProgress(JSON.parse(currentRaw));
    } catch (error) {
      onError("Сохранённый прогресс повреждён; исходная копия сохранена", error);
      return defaultProgress();
    }
  }
  const legacyRaw = storage.getItem(keys.legacy);
  if (legacyRaw === null) return defaultProgress();
  let migrated;
  try {
    migrated = normalizeProgress(JSON.parse(legacyRaw));
  } catch (error) {
    onError("Старый прогресс повреждён; исходная копия сохранена", error);
    return defaultProgress();
  }
  try {
    storage.setItem(keys.current, JSON.stringify(migrated));
    storage.removeItem(keys.legacy);
  } catch (error) {
    onError("Не удалось перенести прогресс; старая копия сохранена", error);
  }
  return migrated;
}

export function mergeProgress(local, remote) {
  const normalizedLocal = normalizeProgress(local);
  if (!remote) return normalizedLocal;
  const normalizedRemote = normalizeProgress(remote);
  const runs = new Map();
  [...normalizedRemote.runs, ...normalizedLocal.runs].forEach(run => runs.set(run.id, run));
  const localIsNewer = new Date(normalizedLocal.updatedAt) >= new Date(normalizedRemote.updatedAt);
  return {
    version: 2,
    updatedAt: new Date().toISOString(),
    settings: localIsNewer ? normalizedLocal.settings : normalizedRemote.settings,
    runs: [...runs.values()].sort((a, b) => new Date(b.completedAt) - new Date(a.completedAt)).slice(0, 100),
    // Без запасного варианта: иначе очищенный (null) активный прогон нельзя
    // отличить от отсутствующего, и завершённая тренировка воскресала бы
    // с проигравшей стороны.
    activeRun: (localIsNewer ? normalizedLocal.activeRun : normalizedRemote.activeRun) || null
  };
}

export function formatHistoryDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function createRunId() {
  return crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
