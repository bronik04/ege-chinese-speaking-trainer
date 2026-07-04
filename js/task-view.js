import { escapeHtml } from "./progress.js";

export function taskMarkup(task, data, state) {
  const { phase, questionIndex, selectedPhoto, photoChoiceMade } = state;
  if (task === 1) {
    const preparationList = phase === "answer" ? "" : `<ol class="prompt-list">${data.questions.map(question => `<li>${escapeHtml(question)}</li>`).join("")}</ol>`;
    const answerPrompt = phase === "answer" ? `<div class="question-focus"><b>Вопрос ${questionIndex + 1} из 5</b>Задайте вопрос, чтобы узнать: ${escapeHtml(data.questions[questionIndex])}.</div>` : "";
    return `<div class="ad-layout"><div><h1 class="task-title">${escapeHtml(data.title)}</h1><p class="task-lead">${escapeHtml(data.situation)} Задайте пять вопросов, чтобы получить дополнительную информацию.</p>${preparationList}${answerPrompt}</div><div><p class="chinese-banner">${escapeHtml(data.banner)}</p><img class="ad-photo" src="${escapeHtml(data.image)}" alt="${escapeHtml(data.imageAlt)}"></div></div>`;
  }
  if (task === 2) {
    const photos = data.images.map((image, index) => {
      const number = index + 1;
      return `<button class="photo-choice ${number === selectedPhoto ? "selected" : ""}" data-photo="${number}" type="button"><img src="${escapeHtml(image)}" alt="Фотография ${number}"><span>Фотография ${number}</span></button>`;
    }).join("");
    return `<h1 class="task-title">${escapeHtml(data.title)}</h1><p class="task-lead">${escapeHtml(data.lead)}</p><ul class="prompt-list">${data.prompts.map(prompt => `<li>${escapeHtml(prompt)}</li>`).join("")}</ul><div class="starter">${escapeHtml(data.starter.replace("{n}", selectedPhoto))}</div><div class="photo-grid ${photoChoiceMade ? "has-selection" : ""}">${photos}</div>`;
  }
  const photos = data.images.map((image, index) => `<div class="photo-choice selected"><img src="${escapeHtml(image)}" alt="${escapeHtml(data.imageLabels[index])}"><span>${escapeHtml(data.imageLabels[index])}</span></div>`).join("");
  return `<h1 class="task-title">${escapeHtml(data.title)}</h1><p class="task-lead">${escapeHtml(data.lead)}</p><ul class="prompt-list">${data.prompts.map(prompt => `<li>${escapeHtml(prompt)}</li>`).join("")}</ul><div class="photo-grid project-photos">${photos}</div>`;
}

export function stepsMarkup(tasks, activeIndex) {
  return tasks.map((task, index) => {
    const state = index < activeIndex ? "done" : index === activeIndex ? "active" : "";
    return `<span class="step-pill ${state}">${index < activeIndex ? "✓ " : ""}Задание ${task}</span>`;
  }).join("");
}

export function formatTime(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export function shortTime(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
