export function prepareRunResume(run) {
  const completedTasks = [...run.completedTasks];
  const currentTask = completedTasks.includes(run.currentTask)
    ? run.tasks.find(task => !completedTasks.includes(task)) ?? run.currentTask
    : run.currentTask;
  return {
    ...run,
    completedTasks,
    currentTask,
    phase: "idle",
  };
}
