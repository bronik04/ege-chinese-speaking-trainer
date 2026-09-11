const text = value => typeof value === "string" ? value : "";

const strings = (value, length) => Array.from(
  { length },
  (_, index) => text(Array.isArray(value) ? value[index] : ""),
);

const taskContent = (number, source = {}) => {
  const task = source && typeof source === "object" && !Array.isArray(source) ? source : {};
  if (number === 1) return {
    situation: text(task.situation),
    banner: text(task.banner),
    questions: strings(task.questions, 5),
    image: text(task.image),
    imageAlt: text(task.imageAlt),
  };
  if (number === 2) return { images: strings(task.images, 3) };
  return {
    title: text(task.title),
    images: strings(task.images, 2),
    imageLabels: strings(task.imageLabels, 2),
  };
};

export function editableMaterialContent(kind, taskNumber, source = {}) {
  const tasks = {
    "1": taskContent(1, source?.["1"]),
    "2": taskContent(2, source?.["2"]),
    "3": taskContent(3, source?.["3"]),
  };
  return kind === "task" ? { [String(taskNumber)]: tasks[String(taskNumber)] } : tasks;
}
