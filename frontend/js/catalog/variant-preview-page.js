import { api } from "../shared/api.js";
import { VariantPreviewError, projectVariantPreview } from "./variant-preview.js";
import { variantPreviewMarkup, variantPreviewStateMarkup } from "./variant-preview-view.js";

function failureKind(error) {
  if (error instanceof VariantPreviewError) return "invalid_material";
  if (error?.status === 403) return "forbidden";
  if (error?.status === 404) return "not_found";
  return "network";
}

export function createVariantPreviewPageController({ request, render, focus }) {
  let generation = 0;

  async function load() {
    const current = ++generation;
    render({ kind: "loading" });
    try {
      const payload = await request();
      const preview = projectVariantPreview(payload?.material);
      if (current !== generation) return;
      render({ kind: "success", preview });
      focus();
    } catch (error) {
      if (current !== generation) return;
      render({ kind: failureKind(error) });
      focus();
    }
  }

  return { load, retry: load };
}

function validVariantId(value) {
  return typeof value === "string" && value.length >= 1 && value.length <= 80 && value.trim() === value;
}

function bootstrap() {
  import("../shared/site-shell.js");
  const title = document.getElementById("variantPreviewTitle");
  const status = document.getElementById("variantPreviewStatus");
  const retry = document.getElementById("variantPreviewRetry");
  const content = document.getElementById("variantPreviewContent");
  const materialId = new URLSearchParams(window.location.search).get("variant");
  let controller = null;

  function focusTitle() {
    title.focus({ preventScroll: true });
  }

  function render(state) {
    if (state.kind === "success") {
      title.textContent = state.preview.label;
      document.title = `${state.preview.label} · Предпросмотр · 口试`;
      status.textContent = "Изображения варианта доступны для просмотра";
      retry.innerHTML = "";
      content.innerHTML = variantPreviewMarkup(state.preview);
      return;
    }
    title.textContent = "Предпросмотр варианта";
    document.title = "Предпросмотр варианта · 口试";
    content.innerHTML = "";
    status.textContent = state.kind === "loading" ? "Загружаем предпросмотр…" : "Предпросмотр недоступен";
    retry.innerHTML = variantPreviewStateMarkup(state);
  }

  retry.addEventListener("click", event => {
    if (event.target.closest("[data-preview-retry]") && controller) controller.retry();
  });

  if (!validVariantId(materialId)) {
    render({ kind: "invalid_request" });
    focusTitle();
    return;
  }
  controller = createVariantPreviewPageController({
    request: () => api(`/api/materials/${encodeURIComponent(materialId)}`),
    render,
    focus: focusTitle,
  });
  controller.load();
}

if (typeof document !== "undefined") bootstrap();
