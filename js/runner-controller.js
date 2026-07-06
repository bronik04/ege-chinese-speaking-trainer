import { api, uploadAudio } from "./api.js";
import { createRunId } from "./progress.js";
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
  let activeAssignment = null;

  const taskData = (task) => ctx.getVariant().tasks[String(task)];
  const durationFor = (task, kind) => {
    if (!$("fastMode").checked) return taskData(task)[kind + "Seconds"];
    if (task === 1) return kind === "prep" ? 8 : 5;
    return kind === "prep" ? 8 : 10;
  };

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
    $("modeLabel").textContent = `${ctx.getVariant().label} · ${mode === "exam" ? "экзамен" : mode === "assignment" ? "задание преподавателя" : "тренировка"}`;
    $("taskContent").innerHTML = taskMarkup(task, taskData(task), { phase, questionIndex, selectedPhoto, photoChoiceMade });
    $("taskPaper").classList.toggle("locked", isLocked);
    $("taskLock").setAttribute("aria-hidden", String(!isLocked));
    document.querySelectorAll("[data-photo]").forEach(button => button.addEventListener("click", () => {
      if (phase === "answer") return;
      selectedPhoto = Number(button.dataset.photo);
      photoChoiceMade = true;
      renderTask();
    }));
    renderSteps();
  }
  
  function startRun(startMode, assignment = null) {
    if (!ctx.getVariant()) return;
    activeAssignment = assignment;
    mode = assignment ? "assignment" : startMode === "exam" ? "exam" : "practice";
    taskQueue = assignment ? [...assignment.tasks] : mode === "exam" ? [1, 2, 3] : [Number(startMode)];
    taskIndex = 0;
    questionIndex = 0;
    selectedPhoto = 1;
    photoChoiceMade = false;
    recordings.forEach(item => URL.revokeObjectURL(item.url));
    recordings = [];
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
      fastMode: $("fastMode").checked,
      assignmentId: assignment?.id || null,
      startedAt: new Date().toISOString()
    };
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
    renderRecordings();
    ctx.showScreen("result");
    if (activeAssignment && ctx.getAccount()?.user?.role === "student") {
      $("submissionStatus").textContent = "Отправляем работу преподавателю…";
      try {
        const payload = await api(`/api/assignments/${activeAssignment.id}/submissions`, {
          method: "POST", body: JSON.stringify({ run: ctx.getProgress().runs[0] })
        });
        for (const recording of recordings) await uploadAudio(payload.submission.id, recording);
        $("submissionStatus").textContent = `Работа отправлена · попытка ${payload.submission.attempt}`;
        ctx.toast("Работа и аудиозаписи отправлены преподавателю");
        await ctx.getAccount().loadStudentAssignments();
      } catch (error) {
        $("submissionStatus").textContent = `Не удалось отправить: ${error.message}. Записи доступны ниже.`;
      }
    } else {
      $("submissionStatus").textContent = "Аудио хранится только в этой вкладке.";
    }
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
    if (recorder?.state === "recording") await stopRecording(`${ctx.getVariant().label} · задание ${taskQueue[taskIndex]} · незавершённая запись`);
    ctx.finalizeActiveRun("interrupted", recordings.length);
    phase = "idle";
    activeAssignment = null;
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
    startRun, ensureMicrophone, startPreparation, skipPhase, exitRun, beep,
    toggleSound, cleanup,
    resetAssignment: () => { activeAssignment = null; },
  };
}
