import { createRunId } from "../shared/progress.js";
import { createRecordingArchive, recordingArchiveFilename } from "./recording-archive.js";
import { prepareRunResume } from "./resume-run.js";
import { formatTime, stepsMarkup, taskMarkup } from "./task-view.js";

const $ = (id) => document.getElementById(id);

export function createRunnerController(ctx) {
  let mode = "exam";
  let taskQueue = [];
  let taskIndex = 0;
  let phase = "idle";
  let questionIndex = 0;
  let selectedPhoto = 1;
  let photoChoiceMade = false;
  let timerId = null;
  let deadline = 0;
  let phaseDuration = 0;
  let stream = null;
  let recorder = null;
  let chunks = [];
  let recordings = [];
  let soundEnabled = true;
  let audioContext = null;
  let completedRun = null;
  let completedTasks = [];
  let completedRecordings = [];

  const taskData = (task) => ctx.getVariant().tasks[String(task)];
  const durationFor = (task, kind) => taskData(task)[`${kind}Seconds`];

  async function ensureMicrophone(showSuccess = false) {
    if (stream?.active) return true;
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicState(false, "Запись не поддерживается браузером");
      return false;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      setMicState(true, "Микрофон готов");
      if (showSuccess) ctx.toast("Микрофон работает — можно начинать");
      return true;
    } catch (error) {
      setMicState(false, "Нет доступа к микрофону");
      ctx.toast("Разрешите доступ к микрофону в настройках браузера");
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
    $("stepList").innerHTML = stepsMarkup(taskQueue, taskIndex);
  }
  
  function renderTask() {
    const task = taskQueue[taskIndex];
    const isLocked = phase === "idle";
    $("taskBadge").textContent = `Задание ${task}`;
    $("phaseCaption").textContent = phase === "answer" ? "Ответ" : phase === "prep" ? "Подготовка" : "До начала";
    $("modeLabel").textContent = `${ctx.getVariant().label} · ${mode === "exam" ? "экзамен" : "тренировка"}`;
    $("taskContent").innerHTML = taskMarkup(task, taskData(task), { phase, questionIndex, selectedPhoto, photoChoiceMade });
    $("taskPaper").classList.toggle("locked", isLocked);
    $("taskContent").setAttribute("aria-hidden", String(isLocked));
    $("taskContent").inert = isLocked;
    $("taskLock").setAttribute("aria-hidden", String(!isLocked));
    document.querySelectorAll("[data-photo]").forEach(button => button.addEventListener("click", () => {
      if (phase === "answer") return;
      selectedPhoto = Number(button.dataset.photo);
      photoChoiceMade = true;
      renderTask();
    }));
    renderSteps();
  }
  
  function startRun(startMode) {
    if (!ctx.getVariant()) return;
    mode = startMode === "exam" ? "exam" : "practice";
    taskQueue = mode === "exam" ? [1, 2, 3] : [Number(startMode)];
    taskIndex = 0;
    questionIndex = 0;
    selectedPhoto = 1;
    photoChoiceMade = false;
    recordings.forEach(item => URL.revokeObjectURL(item.url));
    recordings = [];
    completedRun = null;
    completedTasks = [];
    completedRecordings = [];
    phase = "idle";
    clearTimer();
    ctx.getProgress().activeRun = {
      id: createRunId(),
      variantId: ctx.getVariant().id,
      variantLabel: ctx.getVariant().label,
      mode,
      tasks: [...taskQueue],
      completedTasks: [],
      currentTask: taskQueue[0],
      phase: "idle",
      fastMode: false,
      startedAt: new Date().toISOString()
    };
    ctx.onRunStarted?.(ctx.getProgress().activeRun.id);
    ctx.saveProgressLocal();
    ctx.showScreen("runner");
    renderTask();
    setIdleControls();
  }

  function resumeRun(storedRun) {
    const resumedRun = prepareRunResume(storedRun);
    mode = resumedRun.mode;
    taskQueue = [...resumedRun.tasks];
    taskIndex = taskQueue.indexOf(resumedRun.currentTask);
    questionIndex = 0;
    selectedPhoto = 1;
    photoChoiceMade = false;
    recordings.forEach(item => URL.revokeObjectURL(item.url));
    recordings = [];
    completedRun = null;
    completedTasks = [];
    completedRecordings = [];
    phase = "idle";
    clearTimer();
    ctx.getProgress().activeRun = resumedRun;
    ctx.onRunStarted?.(resumedRun.id);
    ctx.saveProgressLocal();
    ctx.showScreen("runner");
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
    if (ctx.getProgress().activeRun) {
      ctx.getProgress().activeRun.phase = phase;
      ctx.getProgress().activeRun.currentTask = taskQueue[taskIndex];
      ctx.saveProgressLocal();
    }
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
    if (ctx.getProgress().activeRun) {
      ctx.getProgress().activeRun.phase = phase;
      ctx.getProgress().activeRun.currentTask = taskQueue[taskIndex];
      ctx.saveProgressLocal();
    }
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
  
  function stopRecording(label, task = taskQueue[taskIndex], question = null) {
    return new Promise(resolve => {
      if (!recorder || recorder.state === "inactive") return resolve();
      const current = recorder;
      current.onstop = () => {
        const type = current.mimeType || "audio/webm";
        const blob = new Blob(chunks, { type });
        if (blob.size) recordings.push({ label, task, question, blob, url: URL.createObjectURL(blob), type });
        setRecordingIndicator(false);
        resolve();
      };
      current.stop();
    });
  }
  
  async function finishAnswerPart() {
    clearTimer();
    const task = taskQueue[taskIndex];
    const label = task === 1 ? `${ctx.getVariant().label} · задание 1 · вопрос ${questionIndex + 1}` : `${ctx.getVariant().label} · задание ${task}`;
    await stopRecording(label, task, task === 1 ? questionIndex + 1 : null);
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
    ctx.markTaskCompleted(taskQueue[taskIndex]);
    if (taskIndex < taskQueue.length - 1) {
      taskIndex += 1;
      questionIndex = 0;
      selectedPhoto = 1;
      photoChoiceMade = false;
      phase = "idle";
      renderTask();
      setIdleControls();
    } else {
      await finishRun();
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
  
  function setRecordingIndicator(live, text) {
    $("recordingState").classList.toggle("live", live);
    $("recordingState").querySelector("b").textContent = text || (live ? "Идёт запись" : "Запись не идёт");
  }
  
  async function skipPhase() {
    if (phase === "prep") return beginAnswer();
    if (phase === "answer") return finishAnswerPart();
  }
  
  async function finishRun() {
    clearTimer();
    phase = "done";
    ctx.finalizeActiveRun("completed", recordings.length);
    const run = ctx.getProgress().runs[0];
    completedRun = run ? { ...run, tasks: [...run.tasks], completedTasks: [...run.completedTasks] } : null;
    completedTasks = [...(run?.completedTasks || [])];
    completedRecordings = recordings.map(recording => ({ ...recording }));
    renderRecordings();
    ctx.showScreen("result");
    $("submissionStatus").textContent = "Аудио остаётся в этой вкладке, пока вы сами не отправите его на разбор.";
    ctx.onRunFinished?.();
  }
  
  function renderRecordings() {
    $("downloadAllRecordingsBtn").classList.toggle("hidden", !recordings.length);
    if (!recordings.length) {
      $("recordingsList").innerHTML = '<p class="empty-recording">Записей нет. Проверьте разрешение на использование микрофона и попробуйте ещё раз.</p>';
      return;
    }
    $("recordingsList").innerHTML = recordings.map((item, index) => {
      const extension = item.type.includes("mp4") ? "m4a" : "webm";
      return `<div class="recording-item"><div><b>${item.label}</b><small>Запись ${index + 1}</small></div><a class="download-link" href="${item.url}" download="ege-chinese-${index + 1}.${extension}">Скачать</a><audio controls src="${item.url}"></audio></div>`;
    }).join("");
  }

  async function downloadRecordingsArchive() {
    const button = $("downloadAllRecordingsBtn");
    if (!recordings.length || button.disabled) return;
    button.disabled = true;
    button.textContent = "Готовим архив…";
    try {
      const archive = await createRecordingArchive(recordings);
      const url = URL.createObjectURL(archive);
      const link = document.createElement("a");
      link.href = url;
      link.download = recordingArchiveFilename();
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (_) {
      ctx.toast("Не удалось подготовить архив. Попробуйте ещё раз");
    } finally {
      button.disabled = false;
      button.textContent = "Скачать все записи";
    }
  }
  
  async function exitRun() {
    clearTimer();
    if (recorder?.state === "recording") await stopRecording(`${ctx.getVariant().label} · задание ${taskQueue[taskIndex]} · незавершённая запись`);
    ctx.finalizeActiveRun("interrupted", recordings.length);
    phase = "idle";
    ctx.showScreen("home");
  }
  
  function toggleSound() {
    soundEnabled = !soundEnabled;
    $("soundToggle").setAttribute("aria-pressed", String(soundEnabled));
    $("soundToggle").setAttribute("aria-label", soundEnabled ? "Выключить звук" : "Включить звук");
    if (soundEnabled) beep();
  }

  function cleanup() {
    stream?.getTracks().forEach(track => track.stop());
    recordings.forEach(item => URL.revokeObjectURL(item.url));
  }

  return {
    startRun, resumeRun, ensureMicrophone, startPreparation, skipPhase, exitRun, beep,
    toggleSound, cleanup, downloadRecordingsArchive,
    getCompletedRecordings: () => completedRecordings.map(recording => ({ ...recording })),
    getCompletedTasks: () => [...completedTasks],
    getCompletedRun: () => completedRun && { ...completedRun, tasks: [...completedRun.tasks], completedTasks: [...completedRun.completedTasks] },
  };
}
