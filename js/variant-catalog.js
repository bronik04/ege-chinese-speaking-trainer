import { escapeHtml } from "./progress.js";

export function variantKind(id) {
  return id.startsWith("open-") ? "Официальный вариант" : "Демонстрационный вариант";
}

export function filterVariants(variants, year = "all", query = "") {
  const normalized = query.trim().toLocaleLowerCase("ru");
  return variants.filter(variant => {
    const matchesYear = year === "all" || String(variant.year) === String(year);
    const haystack = `${variant.label} ${variant.source} ${variant.year} ${variantKind(variant.id)}`.toLocaleLowerCase("ru");
    return matchesYear && (!normalized || haystack.includes(normalized));
  });
}

export function yearFiltersMarkup(years, activeYear = "all") {
  const buttons = [{ value: "all", label: "Все годы" }, ...years.map(year => ({ value: String(year), label: String(year) }))];
  return buttons.map(item => `<button class="year-filter${item.value === String(activeYear) ? " active" : ""}" type="button" data-year="${item.value}" aria-pressed="${item.value === String(activeYear)}">${item.label}</button>`).join("");
}

export function catalogMarkup(variants) {
  if (!variants.length) return '<p class="catalog-empty">По этому запросу вариантов пока нет.</p>';
  return variants.map(variant => {
    const taskNumbers = variant.kind === "task" ? [variant.taskNumber] : [1, 2, 3];
    const tasks = taskNumbers.map(number => {
      const title = variant.tasks?.[String(number)]?.title || `Задание ${number}`;
      return `<li><b>0${number}</b><span>${escapeHtml(title)}</span></li>`;
    }).join("");
    const image = escapeHtml(
      variant.tasks?.["1"]?.image
      || variant.tasks?.[String(variant.taskNumber)]?.images?.[0]
      || variant.tasks?.["2"]?.images?.[0]
      || variant.tasks?.["3"]?.images?.[0]
      || "",
    );
    const kindLabel = variant.kind === "task"
      ? `Отдельное задание ${variant.taskNumber}`
      : variant.official === false ? "Авторский вариант" : variantKind(variant.id);
    const href = `index.html?variant=${encodeURIComponent(variant.id)}`;
    return `<article class="variant-card" data-variant="${escapeHtml(variant.id)}">
      <div class="variant-card-media"><img src="${image}" alt="" loading="lazy"><span class="variant-year">${escapeHtml(variant.year)}</span></div>
      <div class="variant-card-copy"><p class="variant-kind">${kindLabel}</p><h3>${escapeHtml(variant.label)}</h3>
      <p class="variant-source">${escapeHtml(variant.source)}</p><ol class="variant-tasks">${tasks}</ol>
      <footer class="variant-card-footer"><span class="variant-duration">≈ ${escapeHtml(variant.totalMinutes)} минут</span><a class="variant-open" href="${href}">Открыть →</a></footer></div>
    </article>`;
  }).join("");
}
