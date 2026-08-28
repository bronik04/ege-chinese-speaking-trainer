import { escapeHtml } from "./progress.js";

function rowsMarkup(select) {
  return [...select.options].map(option => {
    const selected = option.value === select.value;
    return `<button class="material-row${selected ? " selected" : ""}" type="button" role="radio" aria-checked="${selected}" tabindex="${selected ? "0" : "-1"}" data-value="${escapeHtml(option.value)}">
      <span class="material-thumb-glyph" aria-hidden="true" lang="zh">题</span>
      <span class="material-copy"><b>${escapeHtml(option.textContent)}</b><small>${selected ? "Текущий материал" : "Выбрать материал"}</small></span>
      ${selected ? '<span class="material-badge">выбран</span><span class="material-check" aria-hidden="true">✓</span>' : '<span class="material-action">выбрать →</span>'}
    </button>`;
  }).join("");
}

export function enhanceMaterialList(select, list) {
  // Сохраняем общий признак готового кастомного контрола для существующих
  // интеграций, хотя главная использует список вместо выпадающего меню.
  select.dataset.projectSelect = "ready";
  const render = () => {
    list.innerHTML = rowsMarkup(select);
    list.setAttribute("role", "radiogroup");
    list.setAttribute("aria-label", select.getAttribute("aria-label") || "Выбор материала");
  };
  const choose = (value) => {
    if (select.value === value) return;
    select.value = value;
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
  };
  list.addEventListener("click", event => {
    const row = event.target.closest("[data-value]");
    if (row) choose(row.dataset.value);
  });
  list.addEventListener("keydown", event => {
    const rows = [...list.querySelectorAll("[data-value]")];
    const index = rows.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = rows[(index + (event.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length];
      next?.focus();
      choose(next?.dataset.value);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(document.activeElement?.dataset.value);
    }
  });
  select.addEventListener("change", render);
  new window.MutationObserver(render).observe(select, { childList: true, subtree: true });
  render();
}
