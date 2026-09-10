import { plural } from "../shared/plural.js";
import { prepareRunResume } from "./resume-run.js";

function taskMinutes(variant, taskNumber) {
  const task = variant.tasks[String(taskNumber)];
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
  const minutes = pending.kind === "restart" && isExam
    ? variant.totalMinutes
    : Math.ceil(tasks.reduce((sum, task) => sum + taskMinutes(variant, task), 0));
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
