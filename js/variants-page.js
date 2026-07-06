import { catalogMarkup, filterVariants, yearFiltersMarkup } from "./variant-catalog.js";

const $ = (id) => document.getElementById(id);
let variants = [];
let activeYear = "all";

function render() {
  const filtered = filterVariants(variants, activeYear, $("variantSearch").value);
  $("variantCatalog").innerHTML = catalogMarkup(filtered);
  $("catalogStatus").textContent = filtered.length === variants.length
    ? `Доступно вариантов: ${filtered.length}`
    : `Найдено вариантов: ${filtered.length} из ${variants.length}`;
  const years = [...new Set(variants.map(item => item.year))].sort((a, b) => b - a);
  $("yearFilters").innerHTML = yearFiltersMarkup(years, activeYear);
}

async function loadVariants() {
  try {
    const response = await fetch("data/variants/index.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const index = await response.json();
    variants = await Promise.all(index.map(async item => {
      const detailResponse = await fetch(item.file);
      if (!detailResponse.ok) throw new Error(`HTTP ${detailResponse.status}`);
      return { ...item, ...await detailResponse.json() };
    }));
    const years = new Set(variants.map(item => item.year));
    $("catalogCount").textContent = variants.length;
    $("catalogYears").textContent = years.size;
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
