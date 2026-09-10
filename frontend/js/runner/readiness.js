import { plural } from "../shared/plural.js";
import { prepareRunResume } from "./resume-run.js";

// Active runs intentionally store progress, not a copy of the material. The
// server-side exam contract fixes these timings, so a stored run can be
// summarized even when another (including task-only) material is selected.
const STANDARD_TASK_TIMINGS = {
  1: { prepSeconds: 90, answerSeconds: 20 },
  2: { prepSeconds: 120, answerSeconds: 120 },
  3: { prepSeconds: 180, answerSeconds: 180 },
};

function taskMinutes(variant, taskNumber, useStandardTimings) {
  const task = useStandardTimings
    ? STANDARD_TASK_TIMINGS[taskNumber]
    : variant.tasks[String(taskNumber)];
  const answerParts = taskNumber === 1 ? 5 : 1;
  return (task.prepSeconds + task.answerSeconds * answerParts) / 60;
}

export function buildReadinessSummary({ variant, pending, activeRun }) {
  const isExam = pending.startMode === "exam";
  const tasks = pending.kind === "resume"
    ? (() => {
        const resumedRun = prepareRunResume(activeRun);
        return resumedRun.tasks.slice(resumedRun.tasks.indexOf(resumedRun.currentTask));
      })()
    : isExam ? [1, 2, 3] : [Number(pending.startMode)];
  const storedRunAction = pending.kind !== "new";
  const minutes = Math.ceil(tasks.reduce(
    (sum, task) => sum + taskMinutes(variant, task, storedRunAction),
    0,
  ));
  const mode = pending.kind === "resume"
    ? isExam ? "Продолжение экзамена" : "Продолжение тренировки"
    : pending.kind === "restart"
      ? isExam ? "Экзамен заново" : "Тренировка заново"
      : isExam ? "Экзамен" : "Тренировка";

  return {
    material: activeRun?.variantLabel || variant.label,
    mode,
    tasks: tasks.length === 1 ? `Задание ${tasks[0]}` : `Задания ${tasks[0]}–${tasks.at(-1)}`,
    duration: `${minutes} ${plural(minutes, "минута", "минуты", "минут")}`,
    action: pending.kind === "resume"
      ? "Продолжить"
      : pending.kind === "restart"
        ? "Начать заново"
        : isExam ? "Начать экзамен" : "Начать тренировку",
  };
}
