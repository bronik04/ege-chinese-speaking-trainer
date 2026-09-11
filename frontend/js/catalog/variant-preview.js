const TASK_TITLES = Object.freeze({
  1: "Задание 1 · Вопросы к объявлению",
  2: "Задание 2 · Описание фотографии",
  3: "Задание 3 · Проектная работа",
});

const IMAGE_COUNTS = Object.freeze({ 1: 1, 2: 3, 3: 2 });

export class VariantPreviewError extends Error {
  constructor() {
    super("invalid_material");
    this.name = "VariantPreviewError";
    this.code = "invalid_material";
  }
}

function invalidMaterial() {
  throw new VariantPreviewError();
}

function fullyDecode(value) {
  let decoded = value;
  while (true) {
    const next = decodeURIComponent(decoded);
    if (next === decoded) return decoded;
    decoded = next;
  }
}

export function isSafeMaterialImageUrl(value) {
  if (typeof value !== "string" || !value || value.trim() !== value) return false;
  let decoded;
  try {
    decoded = fullyDecode(value);
  } catch {
    return false;
  }
  if (/[\\?#\u0000-\u001f\u007f]/u.test(decoded)) return false;
  if (/^\/api\/material-assets\/[1-9]\d*$/u.test(decoded)) return true;

  const prefix = decoded.startsWith("/assets/")
    ? "/assets/"
    : decoded.startsWith("assets/") ? "assets/" : null;
  if (!prefix) return false;
  const path = decoded.slice(prefix.length);
  return path.length > 0 && path.split("/").every(segment => segment && segment !== "." && segment !== "..");
}

function requiredMetadata(material) {
  if (
    !material
    || typeof material !== "object"
    || typeof material.id !== "string"
    || !material.id.trim()
    || typeof material.label !== "string"
    || typeof material.source !== "string"
    || !Number.isInteger(material.year)
    || typeof material.totalMinutes !== "number"
    || !Number.isFinite(material.totalMinutes)
    || material.totalMinutes <= 0
  ) invalidMaterial();
}

function imageText(value, fallback) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function taskImages(task, number) {
  const count = IMAGE_COUNTS[number];
  if (!task || typeof task !== "object" || Array.isArray(task)) invalidMaterial();
  if (number !== 1 && (!Array.isArray(task.images) || task.images.length !== count)) invalidMaterial();

  const sources = number === 1 ? [task.image] : task.images;
  return sources.map((source, index) => {
    const fallback = `Изображение ${index + 1} задания ${number}`;
    const label = number === 3 ? imageText(task.imageLabels?.[index], null) : null;
    const alt = number === 1 ? imageText(task.imageAlt, fallback) : label || fallback;
    return {
      src: isSafeMaterialImageUrl(source) ? source : null,
      alt,
      label,
    };
  });
}

export function projectVariantPreview(material) {
  requiredMetadata(material);
  if (material.kind !== "full" && material.kind !== "task") invalidMaterial();
  if (!material.tasks || typeof material.tasks !== "object" || Array.isArray(material.tasks)) invalidMaterial();

  let numbers;
  if (material.kind === "task") {
    if (!Number.isInteger(material.taskNumber) || !TASK_TITLES[material.taskNumber]) invalidMaterial();
    numbers = [material.taskNumber];
  } else {
    numbers = [1, 2, 3];
  }

  const tasks = numbers.map(number => ({
    number,
    title: TASK_TITLES[number],
    images: taskImages(material.tasks[String(number)], number),
  }));

  return {
    id: material.id,
    label: material.label,
    source: material.source,
    year: material.year,
    kind: material.kind,
    taskNumber: material.kind === "task" ? material.taskNumber : null,
    totalMinutes: material.totalMinutes,
    tasks,
  };
}
