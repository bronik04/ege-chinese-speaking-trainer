const taskKey = entry => [...new Set(entry?.run?.tasks || [])]
  .sort((left, right) => left - right)
  .join(",");

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
