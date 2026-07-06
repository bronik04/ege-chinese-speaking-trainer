import { escapeHtml } from "./progress.js";

const instances = new Map();

function closeAll(except = null) {
  instances.forEach(instance => {
    if (instance !== except) instance.close();
  });
}

function enhanceSelect(select) {
  if (select.dataset.projectSelect === "ready") return;
  select.dataset.projectSelect = "ready";

  const wrapper = document.createElement("div");
  wrapper.className = "project-select";
  select.parentNode.insertBefore(wrapper, select);
  wrapper.append(select);
  select.classList.add("project-select-native");

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "project-select-trigger";
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  if (select.getAttribute("aria-label")) trigger.setAttribute("aria-label", select.getAttribute("aria-label"));
  const value = document.createElement("span");
  value.className = "project-select-value";
  trigger.append(value);

  const menu = document.createElement("div");
  menu.className = "project-select-menu hidden";
  menu.setAttribute("role", "listbox");
  wrapper.append(trigger, menu);

  const close = () => {
    wrapper.classList.remove("open");
    menu.classList.add("hidden");
    trigger.setAttribute("aria-expanded", "false");
  };
  const sync = () => {
    value.textContent = select.selectedOptions[0]?.textContent || "Выберите значение";
    trigger.disabled = select.disabled;
    menu.querySelectorAll("[data-value]").forEach(option => {
      option.setAttribute("aria-selected", String(option.dataset.value === select.value));
    });
  };
  const render = () => {
    menu.innerHTML = [...select.options].map(option => `<button class="project-select-option" type="button" role="option" data-value="${escapeHtml(option.value)}"${option.disabled ? " disabled" : ""}>${escapeHtml(option.textContent)}</button>`).join("");
    sync();
  };
  const open = () => {
    if (trigger.disabled) return;
    closeAll(instance);
    wrapper.classList.add("open");
    menu.classList.remove("hidden");
    trigger.setAttribute("aria-expanded", "true");
  };
  const instance = { close, open, render, select, sync };
  instances.set(select, instance);

  trigger.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    if (wrapper.classList.contains("open")) close();
    else open();
  });
  trigger.addEventListener("keydown", event => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    open();
    const options = [...menu.querySelectorAll(":not(:disabled)[data-value]")];
    const selected = options.find(option => option.getAttribute("aria-selected") === "true");
    (selected || options[0])?.focus();
  });
  menu.addEventListener("click", event => {
    const option = event.target.closest("[data-value]");
    if (!option || option.disabled) return;
    event.preventDefault();
    select.value = option.dataset.value;
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
    sync();
    close();
    trigger.focus();
  });
  menu.addEventListener("keydown", event => {
    const options = [...menu.querySelectorAll(":not(:disabled)[data-value]")];
    const index = options.indexOf(document.activeElement);
    if (event.key === "Escape") {
      close();
      trigger.focus();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      options[(index + direction + options.length) % options.length]?.focus();
    }
  });
  select.addEventListener("change", sync);
  select.form?.addEventListener("reset", () => window.setTimeout(sync));
  new window.MutationObserver(render).observe(select, { childList: true, subtree: true, attributes: true });
  render();
}

export function enhanceProjectSelects(root = document) {
  root.querySelectorAll("select").forEach(enhanceSelect);
}

export function syncProjectSelects() {
  instances.forEach(instance => instance.sync());
}

document.addEventListener("click", () => closeAll());
document.addEventListener("keydown", event => { if (event.key === "Escape") closeAll(); });
