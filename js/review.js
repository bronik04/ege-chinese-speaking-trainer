import { escapeHtml } from "./progress.js";

export const REVIEW_CRITERIA = {
  1: [1, 2, 3, 4, 5].map(number => ({ key: `question${number}`, label: `Вопрос ${number}`, max: 1 })),
  2: [
    { key: "content", label: "Решение коммуникативной задачи", max: 3 },
    { key: "organization", label: "Организация высказывания", max: 2 },
    { key: "language", label: "Языковое оформление", max: 2 },
  ],
  3: [
    { key: "content", label: "Решение коммуникативной задачи", max: 3 },
    { key: "organization", label: "Организация высказывания", max: 2 },
    { key: "language", label: "Языковое оформление", max: 3 },
  ],
};

export function reviewFields(tasks, scores = {}) {
  return tasks.map(task => `<fieldset class="review-task"><legend>Задание ${task}</legend>${REVIEW_CRITERIA[task].map(item => {
    const value = scores?.[task]?.[item.key] ?? 0;
    return `<label><span>${escapeHtml(item.label)} <small>0–${item.max}</small></span><input type="number" name="task-${task}-${item.key}" min="0" max="${item.max}" value="${value}" required></label>`;
  }).join("")}</fieldset>`).join("");
}

export function collectReviewScores(form, tasks) {
  return Object.fromEntries(tasks.map(task => [String(task), Object.fromEntries(
    REVIEW_CRITERIA[task].map(item => [item.key, Number(form.elements[`task-${task}-${item.key}`].value)])
  )]));
}
