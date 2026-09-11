const taskKey = entry => [...new Set(entry?.run?.tasks || [])]
  .sort((left, right) => left - right)
  .join(",");

export class AttemptComparisonError extends Error {
  constructor(code) {
    super(code);
    this.name = "AttemptComparisonError";
    this.code = code;
  }
}

export const isSelectableAttempt = entry => Boolean(
  entry?.runId
  && !entry.recovered
  && entry.run?.status === "completed",
);

export const sameTaskSet = (left, right) => taskKey(left) === taskKey(right);

export function buildComparisonSelection(entries, selectedRunIds = []) {
  const byId = new Map(entries.map(item => [item.runId, item]));
  const selectedIds = [...new Set(selectedRunIds)]
    .filter(id => isSelectableAttempt(byId.get(id)))
    .slice(0, 2);
  const anchor = byId.get(selectedIds[0]);
  const choices = entries.map(item => {
    const selected = selectedIds.includes(item.runId);
    const eligible = isSelectableAttempt(item);
    const compatible = !anchor || sameTaskSet(anchor, item);
    return {
      runId: item.runId,
      selected,
      selectable: eligible && compatible,
      reason: !eligible ? "incomplete" : compatible ? null : "different_tasks",
    };
  });
  return { selectedIds, choices, canCompare: selectedIds.length === 2 };
}

function reviewOrder(left, right) {
  return Number(right.reviewedAt || 0) - Number(left.reviewedAt || 0)
    || Number(right.submittedAt || 0) - Number(left.submittedAt || 0)
    || Number(right.id || 0) - Number(left.id || 0);
}

function taskScore(entry, taskNumber) {
  const request = (entry.reviewRequests || [])
    .filter(item => item.status === "reviewed" && (item.items || []).some(task => task.task === taskNumber))
    .sort(reviewOrder)[0];
  const item = request?.items.find(task => task.task === taskNumber);
  const valid = item
    && Number.isInteger(item.total)
    && item.total >= 0
    && Number.isInteger(item.maximum)
    && item.maximum >= 0
    && item.scores
    && typeof item.scores === "object"
    && !Array.isArray(item.scores);
  return valid ? {
    total: item.total,
    maximum: item.maximum,
    criteria: { ...item.scores },
  } : null;
}

function attemptMetadata(entry) {
  return {
    runId: entry.runId,
    variantId: entry.variantId,
    variantLabel: entry.variantLabel,
    completedAt: entry.run.completedAt,
    tasks: [...entry.run.tasks],
  };
}

function recordingRequestOrder(left, right) {
  return Number(right.submittedAt || 0) - Number(left.submittedAt || 0)
    || Number(right.id || 0) - Number(left.id || 0);
}

function recordingSlots(entry, taskNumber) {
  const positions = taskNumber === 1 ? [1, 2, 3, 4, 5] : [1];
  const byPosition = new Map();
  for (const recording of entry.recordings || []) {
    if (recording.taskNumber === taskNumber && positions.includes(recording.questionNumber)) {
      byPosition.set(recording.questionNumber, { recording: { ...recording }, source: "personal" });
    }
  }
  for (const request of [...(entry.reviewRequests || [])].sort(recordingRequestOrder)) {
    const item = (request.items || []).find(candidate => candidate.task === taskNumber);
    for (const recording of item?.recordings || []) {
      const position = recording.question_number ?? recording.questionNumber ?? 1;
      if (positions.includes(position) && !byPosition.has(position)) {
        byPosition.set(position, { recording: { ...recording }, source: "review" });
      }
    }
  }
  return positions.map(position => {
    const value = byPosition.get(position);
    return {
      key: `${taskNumber}:${position}`,
      label: taskNumber === 1 ? `Вопрос ${position}` : "Ответ",
      recording: value?.recording || null,
      source: value?.source || null,
    };
  });
}

export function buildAttemptComparison(entries, leftRunId, rightRunId) {
  const leftEntry = entries.find(entry => entry.runId === leftRunId);
  const rightEntry = entries.find(entry => entry.runId === rightRunId);
  if (!leftEntry || !rightEntry) throw new AttemptComparisonError("attempt_missing");
  if (!isSelectableAttempt(leftEntry) || !isSelectableAttempt(rightEntry)) {
    throw new AttemptComparisonError("attempt_ineligible");
  }
  if (leftRunId === rightRunId || !sameTaskSet(leftEntry, rightEntry)) {
    throw new AttemptComparisonError("attempt_incompatible");
  }
  const tasks = [...leftEntry.run.tasks].sort((left, right) => left - right).map(number => {
    const leftScore = taskScore(leftEntry, number);
    const rightScore = taskScore(rightEntry, number);
    return {
      number,
      left: { score: leftScore, recordings: recordingSlots(leftEntry, number) },
      right: { score: rightScore, recordings: recordingSlots(rightEntry, number) },
      delta: leftScore && rightScore && leftScore.maximum === rightScore.maximum
        ? rightScore.total - leftScore.total
        : null,
    };
  });
  return {
    left: attemptMetadata(leftEntry),
    right: attemptMetadata(rightEntry),
    tasks,
  };
}
