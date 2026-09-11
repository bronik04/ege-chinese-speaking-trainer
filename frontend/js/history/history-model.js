const runKey = runId => `run:${runId}`;
const recordingKey = recording => `recording:${recording.id}`;
const reviewKey = request => `review:${request.id}`;

const validRunId = value => typeof value === "string" && value.length > 0;

function dateMilliseconds(value, { seconds = false } = {}) {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return 0;
    return seconds ? value * 1000 : value;
  }
  if (typeof value !== "string") return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function uniqueTasks(values) {
  return [...new Set(values.filter(value => Number.isInteger(value) && value >= 1 && value <= 3))]
    .sort((left, right) => left - right);
}

function recoveredEntry(key, runId, source, tasks, sortAt) {
  return {
    key,
    runId,
    run: null,
    variantId: source.variantId || null,
    variantLabel: source.variantLabel || source.variantId || null,
    tasks: uniqueTasks(tasks),
    recordings: [],
    reviewRequests: [],
    latestReview: null,
    recovered: true,
    sortAt,
  };
}

function addTasks(entry, tasks) {
  entry.tasks = uniqueTasks([...entry.tasks, ...tasks]);
}

function fillVariant(entry, source) {
  if (!entry.variantId && source.variantId) entry.variantId = source.variantId;
  if (!entry.variantLabel) entry.variantLabel = source.variantLabel || source.variantId || null;
}

function recordingOrder(left, right) {
  return (left.taskNumber || 0) - (right.taskNumber || 0)
    || (left.questionNumber || 0) - (right.questionNumber || 0)
    || Number(left.id) - Number(right.id);
}

function reviewOrder(left, right) {
  return dateMilliseconds(right.submittedAt, { seconds: true })
    - dateMilliseconds(left.submittedAt, { seconds: true })
    || Number(right.id) - Number(left.id);
}

export function buildHistoryTimeline({ runs = [], recordings = [], reviewRequests = [] }) {
  const entries = new Map();

  for (const run of runs) {
    const key = runKey(run.id);
    entries.set(key, {
      key,
      runId: run.id,
      run,
      variantId: run.variantId || null,
      variantLabel: run.variantLabel || run.variantId || null,
      tasks: uniqueTasks(run.tasks || []),
      recordings: [],
      reviewRequests: [],
      latestReview: null,
      recovered: false,
      sortAt: dateMilliseconds(run.completedAt || run.startedAt),
    });
  }

  for (const recording of recordings) {
    const hasRun = validRunId(recording.runId);
    const key = hasRun ? runKey(recording.runId) : recordingKey(recording);
    const createdAt = dateMilliseconds(recording.createdAt, { seconds: true });
    const entry = entries.get(key) || recoveredEntry(
      key,
      hasRun ? recording.runId : null,
      recording,
      [recording.taskNumber],
      createdAt,
    );
    entry.recordings.push(recording);
    addTasks(entry, [recording.taskNumber]);
    fillVariant(entry, recording);
    if (entry.recovered) entry.sortAt = Math.max(entry.sortAt, createdAt);
    entries.set(key, entry);
  }

  for (const request of reviewRequests) {
    const hasRun = validRunId(request.runId);
    const key = hasRun ? runKey(request.runId) : reviewKey(request);
    const submittedAt = dateMilliseconds(request.submittedAt, { seconds: true });
    const entry = entries.get(key) || recoveredEntry(
      key,
      hasRun ? request.runId : null,
      request,
      request.tasks || [],
      submittedAt,
    );
    entry.reviewRequests.push(request);
    addTasks(entry, request.tasks || []);
    fillVariant(entry, request);
    if (entry.recovered) entry.sortAt = Math.max(entry.sortAt, submittedAt);
    entries.set(key, entry);
  }

  for (const entry of entries.values()) {
    entry.recordings.sort(recordingOrder);
    entry.reviewRequests.sort(reviewOrder);
    entry.latestReview = entry.reviewRequests[0] || null;
  }

  return [...entries.values()].sort((left, right) => right.sortAt - left.sortAt || left.key.localeCompare(right.key));
}
