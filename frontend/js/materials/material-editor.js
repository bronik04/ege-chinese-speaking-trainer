import { api } from "../shared/api.js";
import { enhanceProjectSelects, syncProjectSelects } from "../shared/project-select.js";
import { escapeHtml } from "../shared/progress.js";
import "../shared/site-shell.js";

const $ = id => document.getElementById(id);
let currentId = null;
let currentStatus = "draft";
let materials = [];
let content = {};

const emptyTask = number => number === 1
  ? { situation: "", banner: "", questions: ["", "", "", "", ""], image: "", imageAlt: "" }
  : number === 2 ? { images: ["", "", ""] } : { title: "", images: ["", ""], imageLabels: ["", ""] };

function ensureContent() {
  for (const number of [1, 2, 3]) content[String(number)] ||= emptyTask(number);
}

function renderAssetFields() {
  $("task1Questions").innerHTML = Array.from({ length: 5 }, (_, index) => `<label>Вопрос ${index + 1}<input data-question="${index}" placeholder="Что спросить?"></label>`).join("");
  $("task2Assets").innerHTML = Array.from({ length: 3 }, (_, index) => `<label class="asset-field">Фотография ${index + 1}<input type="file" accept="image/jpeg,image/png,image/webp" data-asset="task2-${index}"><span data-asset-status="task2-${index}">Файл не выбран</span></label>`).join("");
  $("task3Assets").innerHTML = Array.from({ length: 2 }, (_, index) => `<div><label class="asset-label">Подпись ${index + 1}<input data-task3-label="${index}"></label><label class="asset-field">Фотография ${index + 1}<input type="file" accept="image/jpeg,image/png,image/webp" data-asset="task3-${index}"><span data-asset-status="task3-${index}">Файл не выбран</span></label></div>`).join("");
}

function showTasks() {
  const kind = $("materialKind").value;
  const selected = Number($("materialTaskNumber").value);
  $("taskNumberField").classList.toggle("hidden", kind !== "task");
  document.querySelectorAll("[data-task-editor]").forEach(section => {
    section.classList.toggle("hidden", kind === "task" && Number(section.dataset.taskEditor) !== selected);
  });
  syncProjectSelects();
}

function collectContent() {
  ensureContent();
  content["1"] = {
    ...content["1"], situation: $("task1Situation").value.trim(), banner: $("task1Banner").value.trim(),
    imageAlt: $("task1ImageAlt").value.trim(),
    questions: [...document.querySelectorAll("[data-question]")].map(input => input.value.trim()),
  };
  content["3"] = {
    ...content["3"], title: $("task3Title").value.trim(),
    imageLabels: [...document.querySelectorAll("[data-task3-label]")].map(input => input.value.trim()),
  };
  if ($("materialKind").value === "task") {
    const number = $("materialTaskNumber").value;
    return { [number]: content[number] };
  }
  return content;
}

function requestPayload() {
  return {
    slug: $("materialSlug").value.trim().toLowerCase(), kind: $("materialKind").value,
    taskNumber: $("materialKind").value === "task" ? Number($("materialTaskNumber").value) : null,
    title: $("materialTitle").value.trim(), year: Number($("materialYear").value),
    source: $("materialSource").value.trim(), content: collectContent(),
  };
}

async function uploadSelectedAssets(materialId) {
  const inputs = [...document.querySelectorAll("[data-asset]")].filter(input => input.files?.[0]);
  for (const input of inputs) {
    const file = input.files[0];
    const response = await api(`/api/materials/${materialId}/assets`, {
      method: "POST", headers: { "Content-Type": file.type }, body: file,
    });
    const key = input.dataset.asset;
    if (key === "task1-image") content["1"].image = response.asset.url;
    else if (key.startsWith("task2-")) content["2"].images[Number(key.split("-")[1])] = response.asset.url;
    else content["3"].images[Number(key.split("-")[1])] = response.asset.url;
    document.querySelector(`[data-asset-status="${key}"]`).textContent = "Изображение загружено";
    input.value = "";
  }
}

async function saveMaterial(event) {
  event?.preventDefault();
  if (!$("materialForm").reportValidity()) return null;
  $("editorMessage").textContent = "Сохраняем…";
  try {
    let payload = requestPayload();
    if (!currentId) {
      const created = await api("/api/materials", { method: "POST", body: JSON.stringify(payload) });
      currentId = created.material.id;
    } else {
      const updated = await api(`/api/materials/${currentId}`, { method: "PUT", body: JSON.stringify(payload) });
      currentId = updated.material.id;
    }
    await uploadSelectedAssets(currentId);
    payload = requestPayload();
    await api(`/api/materials/${currentId}`, { method: "PUT", body: JSON.stringify(payload) });
    currentStatus = "draft";
    updateStatus();
    await loadMine();
    $("editorMessage").textContent = "Черновик сохранён";
    return currentId;
  } catch (error) {
    $("editorMessage").textContent = error.message;
    return null;
  }
}

async function publishMaterial() {
  const id = await saveMaterial();
  if (!id) return;
  try {
    await api(`/api/materials/${id}/publish`, { method: "POST", body: "{}" });
    currentStatus = "published";
    updateStatus();
    await loadMine();
    $("editorMessage").textContent = "Материал опубликован и доступен в каталоге";
  } catch (error) {
    $("editorMessage").textContent = error.message;
  }
}

function updateStatus() {
  $("materialStatus").textContent = currentStatus === "published" ? "Опубликован" : "Черновик";
  $("previewMaterialBtn").disabled = !currentId;
  $("deleteMaterialBtn").disabled = !currentId;
}

function fillForm(material) {
  currentId = material.id;
  currentStatus = material.status;
  content = JSON.parse(JSON.stringify(material.tasks || {}));
  ensureContent();
  $("materialKind").value = material.kind;
  $("materialTaskNumber").value = material.taskNumber || 1;
  $("materialTitle").value = material.label;
  $("materialSlug").value = material.id;
  $("materialYear").value = material.year;
  $("materialSource").value = material.source;
  $("task1Situation").value = content["1"].situation || "";
  $("task1Banner").value = content["1"].banner || "";
  $("task1ImageAlt").value = content["1"].imageAlt || "";
  document.querySelectorAll("[data-question]").forEach(input => { input.value = content["1"].questions?.[Number(input.dataset.question)] || ""; });
  $("task3Title").value = content["3"].title || "";
  document.querySelectorAll("[data-task3-label]").forEach(input => { input.value = content["3"].imageLabels?.[Number(input.dataset.task3Label)] || ""; });
  for (const [key, value] of Object.entries({
    "task1-image": content["1"].image,
    "task2-0": content["2"].images?.[0], "task2-1": content["2"].images?.[1], "task2-2": content["2"].images?.[2],
    "task3-0": content["3"].images?.[0], "task3-1": content["3"].images?.[1],
  })) document.querySelector(`[data-asset-status="${key}"]`).textContent = value ? "Изображение загружено" : "Файл не выбран";
  $("editorTitle").textContent = material.label || "Новый материал";
  showTasks();
  updateStatus();
}

function newMaterial() {
  currentId = null;
  currentStatus = "draft";
  content = { "1": emptyTask(1), "2": emptyTask(2), "3": emptyTask(3) };
  $("materialForm").reset();
  $("materialYear").value = new Date().getFullYear();
  $("materialSource").value = "Авторский материал";
  $("editorTitle").textContent = "Новый материал";
  fillForm({ id: "", status: "draft", kind: "full", taskNumber: null, label: "", year: new Date().getFullYear(), source: "Авторский материал", tasks: content });
  currentId = null;
  $("materialSlug").value = "";
  updateStatus();
}

async function editMaterial(id) {
  try {
    const payload = await api(`/api/materials/${id}`);
    fillForm(payload.material);
    document.querySelectorAll("[data-edit-material]").forEach(button => button.classList.toggle("active", button.dataset.editMaterial === id));
  } catch (error) { $("editorMessage").textContent = error.message; }
}

async function loadMine() {
  const payload = await api("/api/materials/mine");
  materials = payload.materials;
  $("myMaterials").innerHTML = materials.length ? materials.map(item => `<button class="my-material" type="button" data-edit-material="${escapeHtml(item.id)}"><b>${escapeHtml(item.label)}</b><small>${item.kind === "task" ? `Задание ${item.taskNumber}` : "Полный вариант"} · ${item.status === "published" ? "опубликован" : "черновик"}</small></button>`).join("") : '<p class="editor-empty">Материалов пока нет.</p>';
}

async function deleteMaterial() {
  if (!currentId || !confirm("Архивировать материал? Он перестанет быть доступен другим пользователям.")) return;
  try {
    await api(`/api/materials/${currentId}`, { method: "DELETE", body: "{}" });
    await loadMine();
    newMaterial();
    $("editorMessage").textContent = "Материал архивирован";
  } catch (error) { $("editorMessage").textContent = error.message; }
}

async function initialize() {
  renderAssetFields();
  enhanceProjectSelects();
  try {
    await api("/api/auth/me");
    await loadMine();
    $("editorAccess").classList.add("hidden");
    $("editorLayout").classList.remove("hidden");
    newMaterial();
  } catch (error) {
    $("editorAccess").innerHTML = `<p class="eyebrow">Доступ ограничен</p><h1>Войдите в аккаунт</h1><p>${escapeHtml(error.message)}</p><a class="primary-btn" href="index.html">Перейти к входу</a>`;
  }
}

$("materialKind").addEventListener("change", showTasks);
$("materialTaskNumber").addEventListener("change", showTasks);
$("materialForm").addEventListener("submit", saveMaterial);
$("publishMaterialBtn").addEventListener("click", publishMaterial);
$("newMaterialBtn").addEventListener("click", newMaterial);
$("deleteMaterialBtn").addEventListener("click", deleteMaterial);
$("previewMaterialBtn").addEventListener("click", () => { if (currentId) window.open(`index.html?variant=${encodeURIComponent(currentId)}`, "_blank"); });
$("myMaterials").addEventListener("click", event => { const button = event.target.closest("[data-edit-material]"); if (button) editMaterial(button.dataset.editMaterial); });

initialize();
