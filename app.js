const $ = (id) => document.getElementById(id);

const screens = {
  home: $("homeScreen"),
  runner: $("runnerScreen"),
  result: $("resultScreen")
};

let variantIndex = [];
let variant = null;
const variantCache = new Map();
let mode = "exam";
let taskQueue = [];
let taskIndex = 0;
let phase = "idle";
let questionIndex = 0;
let selectedPhoto = 1;
let timerId = null;
let deadline = 0;
let phaseDuration = 0;
let stream = null;
let recorder = null;
let chunks = [];
let recordings = [];
let soundEnabled = true;
let audioContext = null;

const taskData = (task) => variant.tasks[String(task)];

const durationFor = (task, kind) => {
  if (!$("fastMode").checked) return taskData(task)[`${kind}Seconds`];
  if (task === 1) return kind === "prep" ? 8 : 5;
  return kind === "prep" ? 8 : 10;
};

function showScreen(name) {
  Object.entries(screens).forEach(([key, node]) => node.classList.toggle("hidden", key !== name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.add("hidden"), 3000);
}

function setStartButtonsEnabled(enabled) {
  document.querySelectorAll("[data-start]").forEach(button => { button.disabled = !enabled; });
}

async function initVariants() {
  try {
    const response = await fetch("data/variants/index.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    variantIndex = await response.json();
    $("variantCount").textContent = variantIndex.length;
    $("variantSelect").innerHTML = variantIndex.map(item => `<option value="${item.id}">${item.label}</option>`).join("");
    await loadVariant(variantIndex[0].id);
  } catch (error) {
    $("variantSource").textContent = "Не удалось загрузить задания";
    toast("Запустите проект через локальный сервер");
    console.error("Variant loading failed", error);
  }
}

async function loadVariant(id) {
  setStartButtonsEnabled(false);
  const item = variantIndex.find(entry => entry.id === id);
  if (!item) return;
  try {
    if (!variantCache.has(id)) {
      const response = await fetch(item.file);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      variantCache.set(id, await response.json());
    }
    variant = variantCache.get(id);
    updateVariantUI();
    setStartButtonsEnabled(true);
  } catch (error) {
    toast("Не удалось загрузить выбранный вариант");
    console.error("Variant loading failed", error);
  }
}

function updateVariantUI() {
  $("heroVariant").textContent = `ЕГЭ · ${variant.label}`;
  $("variantSource").textContent = variant.source;
  $("totalMinutes").textContent = variant.totalMinutes;
  $("task1Timing").textContent = `${shortTime(taskData(1).prepSeconds)} + 5 × ${shortTime(taskData(1).answerSeconds)}`;
  $("task2Timing").textContent = `${shortTime(taskData(2).prepSeconds)} + до ${shortTime(taskData(2).answerSeconds)}`;
  $("task3Timing").textContent = `${shortTime(taskData(3).prepSeconds)} + до ${shortTime(taskData(3).answerSeconds)}`;
  $("task3CardTitle").firstChild.textContent = taskData(3).title.startsWith("Сравнение") ? "Сравнение фото" : "Проектная работа";
}

async function ensureMicrophone(showSuccess = false) {
  if (stream?.active) return true;
  if (!navigator.mediaDevices?.getUserMedia) {
    setMicState(false, "Запись не поддерживается браузером");
    return false;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    setMicState(true, "Микрофон готов");
    if (showSuccess) toast("Микрофон работает — можно начинать");
    return true;
  } catch (error) {
    setMicState(false, "Нет доступа к микрофону");
    toast("Разрешите доступ к микрофону в настройках браузера");
    return false;
  }
}

function setMicState(ok, text) {
  $("micDot").className = `status-dot ${ok ? "ok" : "bad"}`;
  $("micStatus").textContent = text;
}

function beep(frequency = 740, duration = .16) {
  if (!soundEnabled) return;
  try {
    audioContext ||= new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(.0001, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(.16, audioContext.currentTime + .015);
    gain.gain.exponentialRampToValueAtTime(.0001, audioContext.currentTime + duration);
    oscillator.connect(gain).connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + duration);
  } catch (_) {}
}

function renderSteps() {
  $("stepList").innerHTML = taskQueue.map((task, index) => {
    const state = index < taskIndex ? "done" : index === taskIndex ? "active" : "";
    return `<span class="step-pill ${state}">${index < taskIndex ? "✓ " : ""}Задание ${task}</span>`;
  }).join("");
}

function taskMarkup(task) {
  const data = taskData(task);
  if (task === 1) {
    const preparationList = phase === "answer" ? "" : `<ol class="prompt-list">${data.questions.map(question => `<li>${question}</li>`).join("")}</ol>`;
    const answerPrompt = phase === "answer" ? `<div class="question-focus"><b>Вопрос ${questionIndex + 1} из 5</b>Задайте вопрос, чтобы узнать: ${data.questions[questionIndex]}.</div>` : "";
    return `<div class="ad-layout"><div><h1 class="task-title">${data.title}</h1><p class="task-lead">${data.situation} Задайте пять вопросов, чтобы получить дополнительную информацию.</p>${preparationList}${answerPrompt}</div><div><p class="chinese-banner">${data.banner}</p><img class="ad-photo" src="${data.image}" alt="${data.imageAlt}"></div></div>`;
  }
  if (task === 2) {
    const photos = data.images.map((image, index) => {
      const number = index + 1;
      return `<button class="photo-choice ${number === selectedPhoto ? "selected" : ""}" data-photo="${number}" type="button"><img src="${image}" alt="Фотография ${number}"><span>Фотография ${number}</span></button>`;
    }).join("");
    return `<h1 class="task-title">${data.title}</h1><p class="task-lead">${data.lead}</p><ul class="prompt-list">${data.prompts.map(prompt => `<li>${prompt}</li>`).join("")}</ul><div class="starter">${data.starter.replace("{n}", selectedPhoto)}</div><div class="photo-grid">${photos}</div>`;
  }
  const photos = data.images.map((image, index) => `<div class="photo-choice selected"><img src="${image}" alt="${data.imageLabels[index]}"><span>${data.imageLabels[index]}</span></div>`).join("");
  return `<h1 class="task-title">${data.title}</h1><p class="task-lead">${data.lead}</p><ul class="prompt-list">${data.prompts.map(prompt => `<li>${prompt}</li>`).join("")}</ul><div class="photo-grid project-photos">${photos}</div>`;
}

function renderTask() {
  const task = taskQueue[taskIndex];
  const isLocked = phase === "idle";
  $("taskBadge").textContent = `Задание ${task}`;
  $("phaseCaption").textContent = phase === "answer" ? "Ответ" : phase === "prep" ? "Подготовка" : "До начала";
  $("modeLabel").textContent = `${variant.label} · ${mode === "exam" ? "экзамен" : "тренировка"}`;
  $("taskContent").innerHTML = taskMarkup(task);
  $("taskPaper").classList.toggle("locked", isLocked);
  $("taskLock").setAttribute("aria-hidden", String(!isLocked));
  document.querySelectorAll("[data-photo]").forEach(button => button.addEventListener("click", () => {
    if (phase === "answer") return;
    selectedPhoto = Number(button.dataset.photo);
    renderTask();
  }));
  renderSteps();
}

function startRun(startMode) {
  if (!variant) return;
  mode = startMode === "exam" ? "exam" : "practice";
  taskQueue = mode === "exam" ? [1, 2, 3] : [Number(startMode)];
  taskIndex = 0;
  questionIndex = 0;
  selectedPhoto = 1;
  recordings.forEach(item => URL.revokeObjectURL(item.url));
  recordings = [];
  phase = "idle";
  clearTimer();
  showScreen("runner");
  renderTask();
  setIdleControls();
}

function setIdleControls() {
  const task = taskQueue[taskIndex];
  $("timerEyebrow").textContent = "Задание закрыто";
  $("timerValue").textContent = formatTime(durationFor(task, "prep"));
  $("timerHint").textContent = "на подготовку";
  $("timerRing").style.setProperty("--progress", 1);
  $("timerRing").classList.remove("urgent");
  $("mainActionBtn").textContent = taskIndex ? "Открыть и начать подготовку" : "Начать подготовку";
  $("mainActionBtn").disabled = false;
  $("mainActionBtn").classList.remove("hidden");
  $("skipBtn").classList.add("hidden");
  setRecordingIndicator(false);
}

function startPreparation() {
  phase = "prep";
  renderTask();
  $("timerEyebrow").textContent = "Время на подготовку";
  $("timerHint").textContent = "до начала записи";
  $("mainActionBtn").classList.add("hidden");
  $("skipBtn").textContent = "Перейти к ответу";
  $("skipBtn").classList.remove("hidden");
  startTimer(durationFor(taskQueue[taskIndex], "prep"), beginAnswer);
}

async function beginAnswer() {
  clearTimer();
  beep(820, .22);
  phase = "answer";
  renderTask();
  $("timerEyebrow").textContent = taskQueue[taskIndex] === 1 ? `Вопрос ${questionIndex + 1} из 5` : "Время ответа";
  $("timerHint").textContent = "идёт запись";
  $("skipBtn").textContent = taskQueue[taskIndex] === 1 && questionIndex < 4 ? "Следующий вопрос" : "Завершить ответ";
  $("skipBtn").classList.remove("hidden");
  await startRecording();
  startTimer(durationFor(taskQueue[taskIndex], "answer"), finishAnswerPart);
}

async function startRecording() {
  const ready = await ensureMicrophone(false);
  if (!ready) {
    setRecordingIndicator(false, "Таймер идёт без записи");
    return;
  }
  if (typeof MediaRecorder === "undefined") {
    setRecordingIndicator(false, "Запись не поддерживается браузером");
    return;
  }
  try {
    chunks = [];
    const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(type => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined);
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.start();
    setRecordingIndicator(true);
  } catch (_) {
    recorder = null;
    setRecordingIndicator(false, "Не удалось начать запись");
  }
}

function stopRecording(label) {
  return new Promise(resolve => {
    if (!recorder || recorder.state === "inactive") return resolve();
    const current = recorder;
    current.onstop = () => {
      const type = current.mimeType || "audio/webm";
      const blob = new Blob(chunks, { type });
      if (blob.size) recordings.push({ label, blob, url: URL.createObjectURL(blob), type });
      setRecordingIndicator(false);
      resolve();
    };
    current.stop();
  });
}

async function finishAnswerPart() {
  clearTimer();
  const task = taskQueue[taskIndex];
  const label = task === 1 ? `${variant.label} · задание 1 · вопрос ${questionIndex + 1}` : `${variant.label} · задание ${task}`;
  await stopRecording(label);
  beep(560, .2);
  if (task === 1 && questionIndex < 4) {
    questionIndex += 1;
    beginAnswer();
    return;
  }
  await advanceTask();
}

async function advanceTask() {
  clearTimer();
  if (taskIndex < taskQueue.length - 1) {
    taskIndex += 1;
    questionIndex = 0;
    selectedPhoto = 1;
    phase = "idle";
    renderTask();
    setIdleControls();
  } else {
    finishRun();
  }
}

function startTimer(seconds, onComplete) {
  clearTimer();
  phaseDuration = seconds;
  deadline = Date.now() + seconds * 1000;
  const tick = () => {
    const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    $("timerValue").textContent = formatTime(left);
    $("timerRing").style.setProperty("--progress", left / phaseDuration);
    $("timerRing").classList.toggle("urgent", left <= 10);
    if (left <= 0) {
      clearTimer();
      onComplete();
    }
  };
  tick();
  timerId = setInterval(tick, 250);
}

function clearTimer() {
  if (timerId) clearInterval(timerId);
  timerId = null;
}

function formatTime(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function shortTime(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function setRecordingIndicator(live, text) {
  $("recordingState").classList.toggle("live", live);
  $("recordingState").querySelector("b").textContent = text || (live ? "Идёт запись" : "Запись не идёт");
}

async function skipPhase() {
  if (phase === "prep") return beginAnswer();
  if (phase === "answer") return finishAnswerPart();
}

function finishRun() {
  clearTimer();
  phase = "done";
  renderRecordings();
  showScreen("result");
}

function renderRecordings() {
  if (!recordings.length) {
    $("recordingsList").innerHTML = '<p class="empty-recording">Записей нет. Проверьте разрешение на использование микрофона и попробуйте ещё раз.</p>';
    return;
  }
  $("recordingsList").innerHTML = recordings.map((item, index) => {
    const extension = item.type.includes("mp4") ? "m4a" : "webm";
    return `<div class="recording-item"><div><b>${item.label}</b><small>Запись ${index + 1}</small></div><a class="download-link" href="${item.url}" download="ege-chinese-${index + 1}.${extension}">Скачать</a><audio controls src="${item.url}"></audio></div>`;
  }).join("");
}

async function exitRun() {
  clearTimer();
  if (recorder?.state === "recording") await stopRecording(`${variant.label} · задание ${taskQueue[taskIndex]} · незавершённая запись`);
  phase = "idle";
  showScreen("home");
}

document.querySelectorAll("[data-start]").forEach(button => button.addEventListener("click", () => startRun(button.dataset.start)));
$("variantSelect").addEventListener("change", event => loadVariant(event.target.value));
$("checkMicBtn").addEventListener("click", () => ensureMicrophone(true));
$("mainActionBtn").addEventListener("click", startPreparation);
$("skipBtn").addEventListener("click", skipPhase);
$("exitBtn").addEventListener("click", exitRun);
$("restartBtn").addEventListener("click", () => showScreen("home"));
$("soundToggle").addEventListener("click", () => {
  soundEnabled = !soundEnabled;
  $("soundToggle").textContent = soundEnabled ? "Звук включён" : "Звук выключен";
  $("soundToggle").setAttribute("aria-pressed", String(soundEnabled));
  if (soundEnabled) beep();
});

window.addEventListener("beforeunload", () => {
  stream?.getTracks().forEach(track => track.stop());
  recordings.forEach(item => URL.revokeObjectURL(item.url));
});

initVariants();
