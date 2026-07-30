import { catalogMarkup, filterVariants, yearFiltersMarkup } from "./variant-catalog.js";
import { plural, pluralize } from "../shared/plural.js";
import "../shared/site-shell.js";

const $ = (id) => document.getElementById(id);
let variants = [];
let activeYear = "all";

function render() {
  const filtered = filterVariants(variants, activeYear, $("variantSearch").value);
  $("variantCatalog").innerHTML = catalogMarkup(filtered);
  $("catalogStatus").textContent = filtered.length === variants.length
    ? `Доступно ${pluralize(filtered.length, "вариант", "варианта", "вариантов")}`
    : `Найдено ${filtered.length} из ${pluralize(variants.length, "варианта", "вариантов", "вариантов")}`;
  const years = [...new Set(variants.map(item => item.year))].sort((a, b) => b - a);
  $("yearFilters").innerHTML = yearFiltersMarkup(years, activeYear);
}

async function loadVariants() {
  try {
    const response = await fetch("/api/materials");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const index = payload.materials;
    variants = await Promise.all(index.map(async item => {
      const detailResponse = await fetch(`/api/materials/${encodeURIComponent(item.id)}`);
      if (!detailResponse.ok) throw new Error(`HTTP ${detailResponse.status}`);
      return { ...item, ...(await detailResponse.json()).material };
    }));
    const years = new Set(variants.map(item => item.year));
    $("catalogCount").textContent = variants.length;
    $("catalogCountLabel").textContent = plural(variants.length, "вариант", "варианта", "вариантов");
    $("catalogYears").textContent = years.size;
    $("catalogYearsLabel").textContent = plural(years.size, "учебный год", "учебных года", "учебных лет");
    render();
  } catch (error) {
    $("catalogStatus").textContent = "Не удалось загрузить каталог. Проверьте подключение к серверу.";
    $("variantCatalog").innerHTML = '<p class="catalog-empty">Каталог временно недоступен.</p>';
    console.error("Variant catalog loading failed", error);
  }
}

$("variantSearch").addEventListener("input", render);
$("yearFilters").addEventListener("click", event => {
  const button = event.target.closest("[data-year]");
  if (!button) return;
  activeYear = button.dataset.year;
  render();
});

loadVariants();
