const $ = (selector) => document.querySelector(selector);

const DATA_BASE = "data/";
const MAX_ITEMS_VISIVEIS = 5000;
const PAGE_SIZE = 60;
const IMAGE_PLACEHOLDER = "static/placeholder.svg";
const STORAGE_KEY = "imoveis-radar-static:overrides:v1";
const NOTICE_KEY = "imoveis-radar-static:notice:v1";
const ANALYTICS_KEY = "imoveis-radar-static:analytics-consent:v1";
const MAP_LAYER_KEY = "imoveis-radar-static:map-layer:v1";
const QUICK_PRESETS_KEY = "imoveis-radar-static:quick-presets:v1";
const MOBILE_LAYOUT = "(max-width: 767px)";
const FILTER_URL_KEYS = [
  "uf", "cidade", "bairro", "financiamento", "modalidade", "fonte", "q",
  "sort", "preco_max", "desconto_min", "lucro_min", "bbox", "exclusoes",
];

const DEFAULTS = {
  uf: "all",
  cidade: "all",
  bairro: "all",
  preco_min: 0,
  preco_max: 0,
  desconto_min: 0,
  lucro_min: 0,
  financiamento: "all",
  modalidade: "all",
  fonte: "all",
  q: "",
  bbox: "",
  aplicar_exclusoes: true,
  sort: "desconto_desc",
};

function emptyLocal() {
  return {
    marketValues: {},
    excludedIds: {},
    unexcludedIds: {},
    excludeLocations: [],
    removedLocations: [],
    settings: null,
  };
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asIdMap(value) {
  const result = {};
  for (const [id, enabled] of Object.entries(asRecord(value))) {
    if (id && enabled) result[id] = true;
  }
  return result;
}

function asLocations(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((entry) => entry && typeof entry === "object" && !Array.isArray(entry))
    .map((entry) => ({
      cidade: typeof entry.cidade === "string" ? entry.cidade.trim() : "",
      bairro:
        typeof entry.bairro === "string" && entry.bairro.trim()
          ? entry.bairro.trim()
          : "all",
      endereco:
        typeof entry.endereco === "string" && entry.endereco.trim()
          ? entry.endereco.trim()
          : "all",
    }))
    .filter((entry) => entry.cidade);
}

function asSettings(value) {
  const record = asRecord(value);
  const settings = {};
  for (const key of ["taxa_venda", "custo_fixo", "custo_fixo_modo", "fator_preco"]) {
    if (Object.prototype.hasOwnProperty.call(record, key)) {
      settings[key] = record[key];
    }
  }
  return Object.keys(settings).length ? settings : null;
}

function asMarketValues(value) {
  const result = {};
  for (const [id, raw] of Object.entries(asRecord(value))) {
    if (!id) continue;
    if (raw === null) {
      result[id] = null;
      continue;
    }
    const numeric = Number(raw);
    if (Number.isFinite(numeric) && numeric > 0) result[id] = numeric;
  }
  return result;
}

function loadLocalOverrides() {
  const base = emptyLocal();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return base;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return base;
    return {
      marketValues: asMarketValues(parsed.marketValues),
      excludedIds: asIdMap(parsed.excludedIds),
      unexcludedIds: asIdMap(parsed.unexcludedIds),
      excludeLocations: asLocations(parsed.excludeLocations),
      removedLocations: Array.isArray(parsed.removedLocations)
        ? parsed.removedLocations.filter((entry) => typeof entry === "string")
        : [],
      settings: asSettings(parsed.settings),
    };
  } catch (error) {
    return base;
  }
}

const state = {
  meta: null,
  manifest: null,
  baseItems: [],
  allItems: [],
  remoteConfig: null,
  local: loadLocalOverrides(),
  items: [],
  total: 0,
  truncated: false,
  visible: PAGE_SIZE,
  filters: { ...DEFAULTS },
  map: null,
  cluster: null,
  tileLayers: null,
  mapLayer: "street",
  fit: true,
  initialized: false,
  facets: null,
  facetsTimer: null,
  mapFilter: false,
  bbox: "",
  firstFetch: true,
  facetsApplying: false,
  dataLoaded: false,
  searchIndex: [],
  suggestionActive: -1,
  suggestionTimer: null,
  mobileMapView: false,
  mobileMapFit: false,
};

const money = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  maximumFractionDigits: 0,
});

function formatBRL(value) {
  return money.format(Number(value) || 0);
}

function formatPct(value) {
  return `${(Number(value) || 0).toFixed(1).replace(".", ",")}%`;
}

function discountLabel(item) {
  if (item.desconto == null) return "s/ avaliação";
  const value = Number(item.desconto) || 0;
  return `${value >= 0 ? "-" : "+"}${formatPct(Math.abs(value))}`;
}

function priceLabel(item) {
  if (item.preco_label) return item.preco_label;
  return item.sem_preco ? "Faça sua oferta" : formatBRL(item.preco);
}

function sourceLabel(item) {
  return item.fonte_nome || item.fonte || "Caixa";
}

function sourceBadge(item) {
  return `<span class="tag source source-${escapeHtml(item.fonte || "caixa")}">${escapeHtml(sourceLabel(item))}</span>`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function shortText(value, limit = 160) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (text.length <= limit) return text;
  return `${text.slice(0, limit).trimEnd()}…`;
}

function safeUrl(value) {
  const text = String(value || "").trim();
  if (!/^https?:\/\//i.test(text)) return "";
  try {
    const parsed = new URL(text);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    return parsed.href;
  } catch (error) {
    return "";
  }
}

function imageSrc(item) {
  const url = safeUrl(item.imagem);
  if (!url || !url.startsWith("https://")) return "";
  const proxy = window.IMOVEIS_CONFIG?.imageProxy;
  if (item.fonte && item.fonte !== "caixa" && proxy) {
    return `${proxy}?url=${encodeURIComponent(url)}`;
  }
  return url;
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function round2(value) {
  return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
}

function normText(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toUpperCase();
}

function normalizeSearch(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function compareText(a, b) {
  const left = normText(a);
  const right = normText(b);
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function uniqueSorted(values) {
  return [...new Set(values.filter((value) => value !== null && value !== undefined && value !== ""))]
    .sort(compareText);
}

function isMobileLayout() {
  return window.matchMedia(MOBILE_LAYOUT).matches;
}

function readStoredValue(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function writeStoredValue(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (error) {
    // Armazenamento indisponível: a preferência vale só para esta sessão.
  }
}

/* --------------------------------------------------------------------------
 * Filtros colapsáveis, presets rápidos e resumo de filtros ativos
 * ------------------------------------------------------------------------ */

const QUICK_PRESETS = {
  desconto: {
    label: "Desconto > 30%",
    apply: (filters) => ({ ...filters, desconto_min: 30 }),
    clear: (filters) => ({ ...filters, desconto_min: 0 }),
    isActive: (filters) => Number(filters.desconto_min) >= 30,
  },
  lucro: {
    label: "Lucro > R$ 50k",
    apply: (filters) => ({ ...filters, lucro_min: 50000 }),
    clear: (filters) => ({ ...filters, lucro_min: 0 }),
    isActive: (filters) => Number(filters.lucro_min) >= 50000,
  },
  financiavel: {
    label: "Financiável",
    apply: (filters) => ({ ...filters, financiamento: "sim" }),
    clear: (filters) => ({ ...filters, financiamento: "all" }),
    isActive: (filters) => filters.financiamento === "sim",
  },
};

function loadQuickPresets() {
  const raw = readStoredValue(QUICK_PRESETS_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((id) => Object.prototype.hasOwnProperty.call(QUICK_PRESETS, id))
      : [];
  } catch (error) {
    return [];
  }
}

function applyQuickPresetsToFilters(filters, ids) {
  let next = { ...filters };
  for (const id of ids) {
    const preset = QUICK_PRESETS[id];
    if (preset) next = preset.apply(next);
  }
  return next;
}

function activeQuickPresetIds(filters) {
  return Object.entries(QUICK_PRESETS)
    .filter(([, preset]) => preset.isActive(filters))
    .map(([id]) => id);
}

function persistQuickPresets(ids) {
  const value = JSON.stringify(ids);
  if (readStoredValue(QUICK_PRESETS_KEY) === value) return;
  writeStoredValue(QUICK_PRESETS_KEY, value);
}

function updateQuickFilters() {
  if (!state.meta) return;
  const filters = readFilters();
  const active = activeQuickPresetIds(filters);
  document.querySelectorAll("[data-preset]").forEach((button) => {
    button.setAttribute("aria-pressed", String(active.includes(button.dataset.preset)));
  });
  persistQuickPresets(active);
}

function toggleQuickPreset(id) {
  const preset = QUICK_PRESETS[id];
  if (!preset) return;
  const current = readFilters();
  const next = preset.isActive(current) ? preset.clear(current) : preset.apply(current);
  applyFiltersToInputs(next);
  scheduleFetch();
  scheduleFacets();
}

const FILTER_CONTROL_SELECTORS = {
  uf: "#combo-uf",
  cidade: "#combo-cidade",
  bairro: "#combo-bairro",
  fonte: "#f-fonte",
  preco_max: "#f-preco-max",
  desconto_min: "#f-desconto-min",
  lucro_min: "#f-lucro-min",
  financiamento: "#f-financiamento",
  modalidade: "#f-modalidade",
  q: "#f-q",
};

function countActiveFilters(filters) {
  let count = 0;
  if (filters.uf !== "all") count += 1;
  if (filters.cidade !== "all") count += 1;
  if (filters.bairro !== "all") count += 1;
  if (filters.fonte !== "all") count += 1;
  if (Number(filters.preco_max) > 0) count += 1;
  if (Number(filters.desconto_min) > 0) count += 1;
  if (Number(filters.lucro_min) > 0) count += 1;
  if (filters.financiamento !== "all") count += 1;
  if (filters.modalidade !== "all") count += 1;
  if (filters.q) count += 1;
  return count;
}

function updateFiltersButton() {
  const button = $("#btn-filters");
  if (!button || !state.meta) return;
  const count = countActiveFilters(readFilters());
  button.textContent = count ? `Filtros (${count})` : "Filtros";
}

function updateActiveFilterControls() {
  if (!state.meta) return;
  const filters = readFilters();
  const active = {
    uf: filters.uf !== "all",
    cidade: filters.cidade !== "all",
    bairro: filters.bairro !== "all",
    fonte: filters.fonte !== "all",
    preco_max: Number(filters.preco_max) > 0,
    desconto_min: Number(filters.desconto_min) > 0,
    lucro_min: Number(filters.lucro_min) > 0,
    financiamento: filters.financiamento !== "all",
    modalidade: filters.modalidade !== "all",
    q: Boolean(filters.q),
  };
  for (const [key, selector] of Object.entries(FILTER_CONTROL_SELECTORS)) {
    $(selector)?.closest("label")?.classList.toggle("filter-active", Boolean(active[key]));
  }
}

function refreshFilterUI() {
  if (!state.meta) return;
  updateQuickFilters();
  updateActiveFilterControls();
  updateFiltersButton();
}

/* --------------------------------------------------------------------------
 * Drawer de filtros no mobile e alternância Lista/Mapa
 * ------------------------------------------------------------------------ */

function openFiltersDrawer() {
  if (!isMobileLayout()) return;
  document.body.classList.add("filters-open");
  $("#filters-backdrop")?.classList.remove("hidden");
  $("#btn-filters")?.setAttribute("aria-expanded", "true");
  // A gaveta usa visibility na transição; o foco só funciona após ela ficar visível.
  setTimeout(() => $("#btn-filters-close")?.focus(), 220);
}

function closeFiltersDrawer() {
  const panel = $("#filters-panel");
  const hadFocus = Boolean(panel?.contains(document.activeElement));
  document.body.classList.remove("filters-open");
  $("#filters-backdrop")?.classList.add("hidden");
  $("#btn-filters")?.setAttribute("aria-expanded", "false");
  if (hadFocus) setTimeout(() => $("#btn-filters")?.focus(), 0);
}

function fitMapToItems() {
  if (!state.map || !window.L) return;
  const points = state.items.filter((item) => item.lat != null && item.lng != null);
  if (!points.length) return;
  state.map.fitBounds(
    L.latLngBounds(points.map((item) => [item.lat, item.lng])),
    { padding: [24, 24], maxZoom: 13 }
  );
}

function resizeMobileMap() {
  const mapElement = $("#map");
  if (!mapElement) return;
  if (!isMobileLayout() || !state.mobileMapView) {
    mapElement.style.height = "";
    state.map?.invalidateSize();
    return;
  }
  const main = document.querySelector("main");
  const foot = document.querySelector(".map-foot");
  const top = main ? main.getBoundingClientRect().top : 0;
  const footHeight = foot ? foot.getBoundingClientRect().height : 0;
  const viewportHeight = window.visualViewport?.height || window.innerHeight;
  // Reserva espaço para o rodapé do mapa e para o botão flutuante Lista/Mapa.
  const available = Math.max(320, viewportHeight - top - footHeight - 84);
  mapElement.style.height = `${available}px`;
  state.map?.invalidateSize();
}

function setMobileView(view) {
  const showMap = view === "map";
  state.mobileMapView = showMap;
  document.body.classList.toggle("mobile-map-view", showMap);
  const button = $("#btn-view-toggle");
  if (button) {
    button.textContent = showMap ? "Ver Lista" : "Ver Mapa";
    button.setAttribute("aria-pressed", String(showMap));
    button.setAttribute("aria-label", showMap ? "Ver lista de imóveis" : "Ver mapa");
  }
  if (showMap) {
    closeFiltersDrawer();
    window.scrollTo({ top: 0, behavior: "auto" });
    requestAnimationFrame(() => {
      resizeMobileMap();
      if (!state.mobileMapFit) {
        if (state.mapFilter && state.bbox) {
          const bounds = boundsFromBbox(state.bbox);
          if (bounds) state.map?.fitBounds(bounds, { padding: [12, 12] });
        } else {
          fitMapToItems();
        }
        state.mobileMapFit = true;
      }
    });
  } else {
    resizeMobileMap();
  }
}

/* --------------------------------------------------------------------------
 * Autocomplete acessível da busca (IDs, cidades e bairros)
 * ------------------------------------------------------------------------ */

function buildSearchIndex() {
  const seen = new Set();
  const entries = [];
  const add = (value, kind, label, weight) => {
    const text = String(value ?? "").trim();
    if (!text) return;
    const key = `${kind}|${normalizeSearch(text)}|${label}`;
    if (seen.has(key)) return;
    seen.add(key);
    entries.push({ value: text, kind, label, search: normalizeSearch(text), weight });
  };

  for (const item of state.allItems) add(item.id, "ID", `ID ${item.id}`, 2);

  for (const [uf, cidades] of Object.entries(state.meta?.cidades || {})) {
    for (const cidade of cidades) add(cidade, "Cidade", `${cidade} — ${uf}`, 0);
  }

  for (const [key, bairros] of Object.entries(state.meta?.bairros || {})) {
    const [uf, cidade] = key.split("|");
    for (const bairro of bairros) add(bairro, "Bairro", `${bairro} — ${cidade}/${uf}`, 1);
  }

  state.searchIndex = entries;
}

function closeSearchSuggestions() {
  clearTimeout(state.suggestionTimer);
  const list = $("#search-suggestions");
  const input = $("#f-q");
  if (list) list.hidden = true;
  if (input) {
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }
  state.suggestionActive = -1;
}

function searchSuggestionsFor(query) {
  const normalized = normalizeSearch(query);
  if (normalized.length < 2) return [];
  const preferIds = /^[0-9]/.test(normalized) || normalized.includes(":");
  const matches = [];
  for (const entry of state.searchIndex) {
    const position = entry.search.indexOf(normalized);
    if (position === -1) continue;
    let weight = entry.weight;
    if (entry.kind === "ID" && preferIds) weight = -1;
    if (entry.kind !== "ID" && preferIds) weight += 3;
    matches.push({ entry, score: (position === 0 ? 0 : 20) + weight, position });
  }
  matches.sort(
    (a, b) =>
      a.score - b.score ||
      a.position - b.position ||
      a.entry.label.localeCompare(b.entry.label, "pt-BR")
  );
  return matches.slice(0, 12).map((match) => match.entry);
}

function updateSearchSuggestions() {
  const input = $("#f-q");
  const list = $("#search-suggestions");
  if (!input || !list || !state.searchIndex.length) return;
  const entries = searchSuggestionsFor(input.value);
  if (!entries.length) {
    closeSearchSuggestions();
    return;
  }
  list.innerHTML = entries
    .map(
      (entry, index) =>
        `<li id="search-suggestion-${index}" role="option" aria-selected="false" data-value="${escapeHtml(entry.value)}"><span class="suggestion-value">${escapeHtml(entry.kind === "ID" ? entry.value : entry.label)}</span><span class="suggestion-kind">${escapeHtml(entry.kind)}</span></li>`
    )
    .join("");
  list.hidden = false;
  input.setAttribute("aria-expanded", "true");
  state.suggestionActive = -1;
}

function moveSearchSuggestion(delta) {
  const input = $("#f-q");
  const list = $("#search-suggestions");
  if (!input || !list || list.hidden) return;
  const options = [...list.querySelectorAll('[role="option"]')];
  if (!options.length) return;
  let next = state.suggestionActive + delta;
  if (next < 0) next = options.length - 1;
  if (next >= options.length) next = 0;
  state.suggestionActive = next;
  options.forEach((option, index) => {
    option.setAttribute("aria-selected", String(index === next));
  });
  input.setAttribute("aria-activedescendant", options[next].id);
  options[next].scrollIntoView({ block: "nearest" });
}

function chooseSearchSuggestion(index) {
  const input = $("#f-q");
  const list = $("#search-suggestions");
  const option = list?.querySelectorAll('[role="option"]')[index];
  if (!input || !option) return;
  input.value = option.dataset.value || "";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  closeSearchSuggestions();
  input.focus();
}

function initSearchAutocomplete() {
  const input = $("#f-q");
  const list = $("#search-suggestions");
  if (!input || !list) return;
  input.addEventListener("input", () => {
    clearTimeout(state.suggestionTimer);
    state.suggestionTimer = setTimeout(updateSearchSuggestions, 90);
  });
  input.addEventListener("focus", () => {
    if (normalizeSearch(input.value).length >= 2) updateSearchSuggestions();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (list.hidden) {
        updateSearchSuggestions();
      } else {
        event.preventDefault();
        moveSearchSuggestion(event.key === "ArrowDown" ? 1 : -1);
      }
      return;
    }
    if (event.key === "Enter" && !list.hidden && state.suggestionActive >= 0) {
      event.preventDefault();
      chooseSearchSuggestion(state.suggestionActive);
      return;
    }
    if (event.key === "Escape" && !list.hidden) {
      event.stopPropagation();
      closeSearchSuggestions();
    }
  });
  list.addEventListener("mousedown", (event) => {
    event.preventDefault();
    const option = event.target.closest('[role="option"]');
    if (option) chooseSearchSuggestion([...list.children].indexOf(option));
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-wrap")) closeSearchSuggestions();
  });
}

function hasURLFilterParams() {
  const params = new URLSearchParams(window.location.search);
  return FILTER_URL_KEYS.some((key) => params.has(key));
}

function filtersFromURL() {
  const params = new URLSearchParams(window.location.search);
  const filters = { ...DEFAULTS };
  for (const key of ["uf", "cidade", "bairro", "financiamento", "modalidade", "fonte", "q", "sort"]) {
    const value = params.get(key);
    if (value !== null && value !== "") filters[key] = value;
  }
  for (const key of ["preco_max", "desconto_min", "lucro_min"]) {
    if (params.has(key)) filters[key] = numberOr(params.get(key), DEFAULTS[key]);
  }
  if (params.has("bbox")) filters.bbox = params.get("bbox") || "";
  if (params.has("exclusoes")) {
    const value = params.get("exclusoes").toLowerCase();
    filters.aplicar_exclusoes = !["0", "false", "nao", "não"].includes(value);
  }
  return filters;
}

function syncURL(filters) {
  const params = new URLSearchParams();
  const set = (key, value) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, value);
  };
  if (filters.uf !== "all") set("uf", filters.uf);
  if (filters.cidade !== "all") set("cidade", filters.cidade);
  if (filters.bairro !== "all") set("bairro", filters.bairro);
  if (filters.fonte !== "all") set("fonte", filters.fonte);
  if (Number(filters.preco_max) > 0) set("preco_max", filters.preco_max);
  if (Number(filters.desconto_min) > 0) set("desconto_min", filters.desconto_min);
  if (Number(filters.lucro_min) > 0) set("lucro_min", filters.lucro_min);
  if (filters.financiamento !== "all") set("financiamento", filters.financiamento);
  if (filters.modalidade !== "all") set("modalidade", filters.modalidade);
  if (filters.q) set("q", filters.q);
  if (filters.sort && filters.sort !== DEFAULTS.sort) set("sort", filters.sort);
  if (filters.bbox) set("bbox", filters.bbox);
  if (!filters.aplicar_exclusoes) set("exclusoes", "0");

  const query = params.toString();
  const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(null, "", next);
}

function copyTextFallback(text) {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  return ok;
}

async function copyShareLink() {
  if (state.mapFilter) state.bbox = currentMapBbox();
  const filters = readFilters();
  syncURL(filters);
  const url = window.location.href;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(url);
      showToast("Link copiado.");
      return;
    }
    if (copyTextFallback(url)) {
      showToast("Link copiado.");
      return;
    }
    window.prompt("Copie o link com os filtros:", url);
  } catch (error) {
    if (copyTextFallback(url)) {
      showToast("Link copiado.");
    } else {
      window.prompt("Copie o link com os filtros:", url);
    }
  }
}

function hideToastAction() {
  const action = $("#toast-action");
  if (!action) return;
  action.classList.add("hidden");
  action.textContent = "";
  action.onclick = null;
}

function hideToast() {
  const toast = $("#toast");
  if (!toast) return;
  clearTimeout(showToast.timer);
  toast.classList.remove("show", "actionable");
  hideToastAction();
}

function showToast(message, options = false) {
  const toast = $("#toast");
  const text = $("#toast-message");
  const action = $("#toast-action");
  if (!toast || !text) return;
  const config = typeof options === "boolean" ? { isError: options } : (options || {});
  text.textContent = message;
  toast.classList.toggle("error", Boolean(config.isError));
  toast.classList.remove("actionable");
  hideToastAction();
  if (config.actionLabel && typeof config.onAction === "function") {
    action.textContent = config.actionLabel;
    action.classList.remove("hidden");
    action.onclick = () => {
      hideToast();
      config.onAction();
    };
    toast.classList.add("actionable");
  }
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  const duration = Number(config.duration) || 3500;
  showToast.timer = setTimeout(() => {
    toast.classList.remove("show", "actionable");
    hideToastAction();
  }, duration);
}

/* --------------------------------------------------------------------------
 * Tooltips acessíveis (hover, foco e toque) com posicionamento inteligente.
 * ------------------------------------------------------------------------ */

const tooltipState = { trigger: null, pinned: false };

function tooltipBubble() {
  return $("#tooltip-bubble");
}

function positionTooltip(trigger) {
  const bubble = tooltipBubble();
  if (!bubble || bubble.hidden) return;
  const rect = trigger.getBoundingClientRect();
  const margin = 8;
  bubble.style.left = "0px";
  bubble.style.top = "0px";
  const box = bubble.getBoundingClientRect();
  let left = rect.left + rect.width / 2 - box.width / 2;
  left = Math.max(margin, Math.min(left, window.innerWidth - box.width - margin));
  let top = rect.bottom + margin;
  if (top + box.height > window.innerHeight - margin) {
    top = rect.top - box.height - margin;
  }
  top = Math.max(margin, Math.min(top, window.innerHeight - box.height - margin));
  bubble.style.left = `${Math.round(left)}px`;
  bubble.style.top = `${Math.round(top)}px`;
}

function showTooltip(trigger, pinned = false) {
  const bubble = tooltipBubble();
  const id = trigger?.dataset?.tooltipId;
  const source = id ? document.getElementById(id) : null;
  if (!bubble || !source) return;
  if (tooltipState.trigger !== trigger) tooltipState.pinned = false;
  tooltipState.trigger = trigger;
  tooltipState.pinned = pinned;
  bubble.textContent = source.textContent.trim();
  bubble.hidden = false;
  trigger.setAttribute("aria-expanded", "true");
  positionTooltip(trigger);
}

function hideTooltip() {
  const bubble = tooltipBubble();
  if (bubble) {
    bubble.hidden = true;
    bubble.textContent = "";
  }
  if (tooltipState.trigger) tooltipState.trigger.removeAttribute("aria-expanded");
  tooltipState.trigger = null;
  tooltipState.pinned = false;
}

function bindTooltips() {
  document.addEventListener("pointerover", (event) => {
    const trigger = event.target.closest("[data-tooltip-id]");
    if (!trigger || trigger === tooltipState.trigger) return;
    showTooltip(trigger);
  });
  document.addEventListener("pointerout", (event) => {
    const trigger = event.target.closest("[data-tooltip-id]");
    if (!trigger || tooltipState.pinned) return;
    if (!trigger.contains(event.relatedTarget)) hideTooltip();
  });
  document.addEventListener("focusin", (event) => {
    const trigger = event.target.closest("[data-tooltip-id]");
    if (trigger) showTooltip(trigger);
  });
  document.addEventListener("focusout", (event) => {
    const trigger = event.target.closest("[data-tooltip-id]");
    if (!trigger || tooltipState.pinned) return;
    hideTooltip();
  });
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-tooltip-id]");
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
      if (tooltipState.trigger === trigger && tooltipState.pinned) hideTooltip();
      else showTooltip(trigger, true);
      return;
    }
    if (tooltipState.trigger && tooltipState.pinned) hideTooltip();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !tooltipState.trigger) return;
    const trigger = tooltipState.trigger;
    hideTooltip();
    trigger.blur?.();
  });
  window.addEventListener("resize", () => {
    if (tooltipState.trigger) positionTooltip(tooltipState.trigger);
  }, { passive: true });
  window.addEventListener("scroll", () => {
    if (tooltipState.trigger) positionTooltip(tooltipState.trigger);
  }, { passive: true, capture: true });
}

function noticeSeen() {
  try {
    return window.localStorage.getItem(NOTICE_KEY) === "1";
  } catch (error) {
    return false;
  }
}

function openNotice() {
  const dialog = $("#notice-dialog");
  const analytics = $("#notice-analytics");
  if (analytics) analytics.checked = analyticsConsent();
  if (dialog && !dialog.open) dialog.showModal();
}

function analyticsConsent() {
  try {
    return window.localStorage.getItem(ANALYTICS_KEY) === "granted";
  } catch (error) {
    return false;
  }
}

function setAnalyticsConsent(granted) {
  const previous = analyticsConsent();
  try {
    window.localStorage.setItem(ANALYTICS_KEY, granted ? "granted" : "denied");
  } catch (error) {
    // Sem localStorage, o GTM não é carregado.
  }
  if (granted) {
    window.__loadGTM?.();
    return;
  }
  if (previous && window.__gtmLoaded) {
    // O GTM não pode ser descarregado sem recarregar a página.
    window.location.reload();
  }
}

function acceptNotice() {
  const analytics = $("#notice-analytics");
  setAnalyticsConsent(Boolean(analytics?.checked));
  try {
    window.localStorage.setItem(NOTICE_KEY, "1");
  } catch (error) {
    // Sem localStorage, o aviso volta na próxima visita.
  }
  const dialog = $("#notice-dialog");
  if (dialog) dialog.close();
}

function declineNotice() {
  // Redirecionamento simples e garantido. window.close() não é confiável
  // em abas abertas pelo usuário.
  try {
    window.localStorage.setItem(ANALYTICS_KEY, "denied");
  } catch (error) {
    // Sem localStorage, nada a limpar.
  }
  window.location.replace("https://www.google.com/");
}

function showNoticeIfNeeded() {
  if (!noticeSeen()) openNotice();
}

function openHelp() {
  const dialog = $("#help-dialog");
  if (dialog && !dialog.open) dialog.showModal();
}

function openFeedback() {
  const dialog = $("#feedback-dialog");
  if (!dialog) return;
  const config = window.IMOVEIS_CONFIG || {};
  const frame = $("#feedback-frame");
  const external = $("#feedback-external");
  if (external && config.feedbackUrl) external.href = config.feedbackUrl;
  if (!config.feedbackEmbedUrl) {
    if (config.feedbackUrl) {
      window.open(config.feedbackUrl, "_blank", "noopener,noreferrer");
    } else {
      showToast("Formulário de sugestões indisponível.", true);
    }
    return;
  }
  if (frame && !frame.getAttribute("src")) frame.src = config.feedbackEmbedUrl;
  if (!dialog.open) dialog.showModal();
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) {
    throw new Error(`Erro ${response.status} ao carregar ${url}`);
  }
  return response.json();
}

/* --------------------------------------------------------------------------
 * Configuração local (localStorage) e recálculo dos campos derivados.
 * ------------------------------------------------------------------------ */

function saveLocalOverrides() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.local));
  } catch (error) {
    showToast("Não foi possível salvar os ajustes neste navegador.", true);
  }
}

function effectiveSettings() {
  return {
    ...(state.meta?.settings || {}),
    ...(state.local.settings || {}),
  };
}

function locationKey(location) {
  return `${normText(location.cidade)}|${normText(location.bairro)}|${normText(location.endereco)}`;
}

function effectiveLocations() {
  const baked = state.remoteConfig?.exclude_locations || [];
  const removed = new Set(state.local.removedLocations || []);
  const bakedFiltered = baked.filter((location) => !removed.has(locationKey(location)));
  const local = state.local.excludeLocations || [];
  const seen = new Set();
  const result = [];
  for (const location of [...bakedFiltered, ...local]) {
    const key = locationKey(location);
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(location);
  }
  return result;
}

function matchesLocalLocation(item, locations) {
  for (const location of locations) {
    const cidade = normText(location.cidade);
    const bairro = normText(location.bairro);
    const endereco = normText(location.endereco);
    if (!cidade || normText(item.cidade) !== cidade) continue;
    if (bairro === "ALL" && endereco === "ALL") return true;
    if (bairro === "ALL") {
      const prefix = endereco.endsWith("*") ? endereco.slice(0, -1) : endereco;
      if (normText(item.endereco).startsWith(prefix)) return true;
      continue;
    }
    if (normText(item.bairro) !== bairro) continue;
    if (endereco === "ALL") return true;
    const prefix = endereco.endsWith("*") ? endereco.slice(0, -1) : endereco;
    if (normText(item.endereco).startsWith(prefix)) return true;
  }
  return false;
}

function applyLocalOverrides(item, settings, locations) {
  const copy = { ...item };
  const preco = Number(item.preco) || 0;
  const bakedAdjusted = Boolean(item.ajustado);
  const bakedValue = bakedAdjusted ? item.valor_ajustado : item.valor_avaliacao;
  const hasLocal = Object.prototype.hasOwnProperty.call(state.local.marketValues, item.id);
  const localValue = state.local.marketValues[item.id];

  let valor;
  let adjusted;
  if (hasLocal) {
    if (localValue === null) {
      valor = item.valor_avaliacao;
      adjusted = false;
    } else {
      valor = Number(localValue);
      adjusted = true;
    }
  } else {
    valor = bakedValue;
    adjusted = bakedAdjusted;
  }
  if (!Number.isFinite(valor) || valor <= 0) {
    valor = null;
  }

  copy.preco = preco;
  copy.valor_avaliacao = item.valor_avaliacao == null ? null : Number(item.valor_avaliacao);
  copy.valor_ajustado = valor == null ? null : round2(valor);
  copy.ajustado = adjusted;
  copy.sem_avaliacao = valor == null;
  copy.sem_preco = preco <= 0;
  copy.preco_label = copy.sem_preco
    ? (item.fonte === "itau" ? "Sob consulta" : "Faça sua oferta")
    : null;

  if (valor == null) {
    copy.desconto = null;
    copy.lucro = null;
    copy.lucro_pct = null;
  } else {
    copy.desconto = round2(((valor - preco) / valor) * 100);
    const modalidade = normText(item.modalidade);
    const fator = ["VENDA ONLINE", "VENDA DIRETA ONLINE"].includes(modalidade)
      ? 1
      : Number(settings.fator_preco ?? 1.05);
    const custo = Number(settings.custo_fixo || 0);
    const custoFixo = settings.custo_fixo_modo === "percentual"
      ? (valor * custo) / 100
      : custo;
    const lucro = valor - valor * Number(settings.taxa_venda || 0) - custoFixo - preco * fator;
    copy.lucro = round2(lucro);
    copy.lucro_pct = round2((lucro / valor) * 100);
  }

  const localExcluded = Boolean(state.local.excludedIds[item.id]);
  const unexcluded = Boolean(state.local.unexcludedIds[item.id]);
  let excluded = localExcluded || (Boolean(item.excluido) && !unexcluded);
  let reason = localExcluded
    ? "Excluído localmente (navegador)"
    : unexcluded
      ? null
      : item.motivo_exclusao;
  if (!localExcluded && !Boolean(item.excluido) && matchesLocalLocation(copy, locations)) {
    excluded = true;
    reason = "Local excluído localmente (navegador)";
  }
  copy.excluido = excluded;
  copy.motivo_exclusao = reason;

  return copy;
}

function recomputeAllItems() {
  const settings = effectiveSettings();
  const locations = effectiveLocations();
  state.allItems = state.baseItems.map((item) =>
    applyLocalOverrides(item, settings, locations)
  );
}

function buildEffectiveConfig() {
  const baked = state.remoteConfig || {};
  const ids = new Set(baked.exclude_ids || []);
  for (const id of Object.keys(state.local.excludedIds || {})) ids.add(id);
  for (const id of Object.keys(state.local.unexcludedIds || {})) ids.delete(id);

  const marketValues = { ...(baked.market_values || {}) };
  for (const [id, value] of Object.entries(state.local.marketValues || {})) {
    if (value === null) delete marketValues[id];
    else marketValues[id] = Number(value);
  }
  const sortedMarket = {};
  for (const key of Object.keys(marketValues).sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true }))) {
    sortedMarket[key] = marketValues[key];
  }
  return {
    settings: effectiveSettings(),
    exclude_ids: [...ids].sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true })),
    exclude_locations: effectiveLocations(),
    market_values: sortedMarket,
  };
}

/* --------------------------------------------------------------------------
 * Filtros, ordenação e facetas (porta fiel de caixa_data.py).
 * ------------------------------------------------------------------------ */

function filterItems(items, params, applyExclusions = true) {
  const uf = String(params.uf || "all").trim();
  const cidade = String(params.cidade || "all").trim();
  const bairro = String(params.bairro || "all").trim();
  const precoMin = Number(params.preco_min) || 0;
  const precoMax = Number(params.preco_max) || Infinity;
  const descontoMin = Number(params.desconto_min) || 0;
  const lucroMin = Number(params.lucro_min) || 0;
  const financiamento = String(params.financiamento || "all").trim().toLowerCase();
  const modalidade = String(params.modalidade || "all").trim();
  const fonte = String(params.fonte || "all").trim().toLowerCase();
  const query = normText(params.q || "");
  let bboxValues = null;
  const bbox = String(params.bbox || "").trim();
  if (bbox) {
    const values = bbox.split(",").map(Number);
    if (values.length === 4 && values.every(Number.isFinite)) bboxValues = values;
  }

  const ufValues = uf.toLowerCase() === "all"
    ? null
    : new Set(uf.split(",").map((value) => normText(value)).filter(Boolean));
  const cidadeValue = cidade.toLowerCase() === "all" ? null : normText(cidade);
  const bairroValue = bairro.toLowerCase() === "all" ? null : normText(bairro);
  const modalidadeValue = modalidade.toLowerCase() === "all" ? null : normText(modalidade);
  const fonteValue = fonte === "all" ? null : fonte;

  return items.filter((item) => {
    if (applyExclusions && item.excluido) return false;
    if (ufValues && !ufValues.has(normText(item.uf))) return false;
    if (cidadeValue && normText(item.cidade) !== cidadeValue) return false;
    if (bairroValue && normText(item.bairro) !== bairroValue) return false;
    if (item.preco < precoMin || item.preco > precoMax) return false;
    if (item.desconto == null) {
      if (descontoMin > 0) return false;
    } else if (item.desconto < descontoMin) {
      return false;
    }
    if (item.lucro == null) {
      if (lucroMin > 0) return false;
    } else if (item.lucro < lucroMin) {
      return false;
    }
    if (financiamento === "sim" && normText(item.financiamento) !== "SIM") return false;
    if (financiamento === "nao" && normText(item.financiamento) === "SIM") return false;
    if (modalidadeValue && normText(item.modalidade) !== modalidadeValue) return false;
    if (fonteValue && (item.fonte || "caixa") !== fonteValue) return false;
    if (bboxValues) {
      const [minLat, minLng, maxLat, maxLng] = bboxValues;
      if (item.lat == null || item.lng == null) return false;
      if (!(minLat <= item.lat && item.lat <= maxLat && minLng <= item.lng && item.lng <= maxLng)) {
        return false;
      }
    }
    if (query) {
      const haystack = normText([
        item.id,
        item.uf,
        item.cidade,
        item.bairro,
        item.endereco,
        item.descricao,
        item.modalidade,
      ].join(" "));
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

function metricSort(items, key) {
  return [...items].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    const an = av == null ? 0 : 1;
    const bn = bv == null ? 0 : 1;
    if (an !== bn) return bn - an;
    if (av == null && bv == null) return 0;
    return Number(bv) - Number(av);
  });
}

function sortItems(items, sortKey) {
  if (sortKey === "preco_asc") {
    return [...items].sort((a, b) => a.preco - b.preco);
  }
  if (sortKey === "preco_desc") {
    return [...items].sort((a, b) => b.preco - a.preco);
  }
  if (sortKey === "lucro_desc") return metricSort(items, "lucro");
  if (sortKey === "lucro_pct_desc") return metricSort(items, "lucro_pct");
  if (sortKey === "endereco") {
    return [...items].sort((a, b) =>
      compareText(a.uf, b.uf) ||
      compareText(a.cidade, b.cidade) ||
      compareText(a.bairro, b.bairro) ||
      compareText(a.endereco, b.endereco)
    );
  }
  return metricSort(items, "desconto");
}

/* --------------------------------------------------------------------------
 * Combos (typeahead)
 * ------------------------------------------------------------------------ */

function comboRoot(target) {
  return typeof target === "string" ? $(target) : target;
}

function comboValue(target) {
  const root = comboRoot(target);
  return root?.querySelector("[data-combo-value]")?.value || "all";
}

function comboSelectedOption(root) {
  return (root._options || []).find((option) => option.value === root._value) || root._options?.[0];
}

function renderCombo(root, query) {
  const list = root.querySelector("[data-combo-list]");
  const term = normalizeSearch(query);
  const options = (root._options || []).filter(
    (option) => !term || normalizeSearch(option.label).includes(term)
  );
  root._filtered = options;
  root._active = -1;
  if (!options.length) {
    list.innerHTML = `<li class="combo-empty">Nenhuma opção</li>`;
    return;
  }
  list.innerHTML = options
    .map(
      (option) =>
        `<li class="combo-option${option.value === root._value ? " selected" : ""}" role="option" data-value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</li>`
    )
    .join("");
}

function openCombo(root) {
  root.classList.add("open");
  root.querySelector("[data-combo-input]").setAttribute("aria-expanded", "true");
}

function closeCombo(root) {
  root.classList.remove("open");
  root.querySelector("[data-combo-input]").setAttribute("aria-expanded", "false");
}

function resetComboText(root) {
  const input = root.querySelector("[data-combo-input]");
  const selected = comboSelectedOption(root);
  if (selected) input.value = selected.label;
}

function selectCombo(root, value) {
  const option = (root._options || []).find((entry) => entry.value === value);
  if (!option) return;
  root._value = option.value;
  root.querySelector("[data-combo-value]").value = option.value;
  root.querySelector("[data-combo-input]").value = option.label;
  closeCombo(root);
  root.querySelector("[data-combo-value]").dispatchEvent(new Event("change", { bubbles: true }));
}

function moveComboActive(root, delta) {
  const items = [...root.querySelectorAll(".combo-option")];
  if (!items.length) return;
  root._active = Math.max(0, Math.min(items.length - 1, (root._active ?? -1) + delta));
  items.forEach((item, index) => item.classList.toggle("active", index === root._active));
  items[root._active].scrollIntoView({ block: "nearest" });
}

function buildCombo(target, allLabel = "Todas") {
  const root = comboRoot(target);
  if (!root) return null;
  if (!root.querySelector("[data-combo-input]")) {
    root.innerHTML = `
      <div class="combo-control">
        <input type="text" data-combo-input role="combobox" autocomplete="off" aria-autocomplete="list" aria-expanded="false" placeholder="${escapeHtml(allLabel)}">
        <button type="button" class="combo-toggle" data-combo-toggle aria-label="Abrir opções">▾</button>
      </div>
      <input type="hidden" data-combo-value value="all">
      <ul class="combo-list" data-combo-list role="listbox"></ul>
    `;
    root._allLabel = allLabel;
    root._options = [{ value: "all", label: allLabel }];
    root._value = "all";
    initCombo(root);
  }
  return root;
}

function comboSet(target, values, current, allLabel) {
  const root = buildCombo(target, allLabel);
  if (!root) return;
  const options = [{ value: "all", label: allLabel }];
  for (const value of values || []) options.push({ value, label: value });
  root._options = options;
  root._allLabel = allLabel;
  const selected = options.find((option) => option.value === current) || options[0];
  const input = root.querySelector("[data-combo-input]");
  const hidden = root.querySelector("[data-combo-value]");
  const typing = document.activeElement === input && root.classList.contains("open");
  if (typing) {
    if (!options.some((option) => option.value === root._value)) {
      root._value = selected.value;
      hidden.value = selected.value;
    }
    renderCombo(root, input.value);
    return;
  }
  root._value = selected.value;
  hidden.value = selected.value;
  input.value = selected.label;
  input.placeholder = allLabel;
  if (root.classList.contains("open")) renderCombo(root, "");
  else root._filtered = options;
}

function comboSetDisabled(target, disabled) {
  const root = buildCombo(target, "Todos");
  if (!root) return;
  const input = root.querySelector("[data-combo-input]");
  input.disabled = disabled;
  root.classList.toggle("disabled", disabled);
  if (disabled) {
    closeCombo(root);
    comboSet(root, [], "all", root._allLabel || "Todos");
  }
}

function initCombo(target) {
  const root = comboRoot(target);
  if (!root || root._comboReady) return;
  root._comboReady = true;
  const input = root.querySelector("[data-combo-input]");
  const list = root.querySelector("[data-combo-list]");
  const toggle = root.querySelector("[data-combo-toggle]");

  input.addEventListener("focus", () => {
    openCombo(root);
    renderCombo(root, "");
    input.select();
  });
  input.addEventListener("input", () => {
    openCombo(root);
    renderCombo(root, input.value);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!root.classList.contains("open")) openCombo(root);
      moveComboActive(root, event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const option = root._filtered?.[root._active] || (root._filtered?.length === 1 ? root._filtered[0] : null);
      if (option) selectCombo(root, option.value);
      else {
        closeCombo(root);
        resetComboText(root);
      }
      return;
    }
    if (event.key === "Escape") {
      if (root.classList.contains("open")) event.stopPropagation();
      closeCombo(root);
      resetComboText(root);
      input.blur();
    }
  });
  input.addEventListener("blur", () => {
    setTimeout(() => {
      if (!root.contains(document.activeElement)) {
        const term = normalizeSearch(input.value);
        const match = (root._options || []).find(
          (option) => normalizeSearch(option.label) === term
        );
        if (match && match.value !== root._value) {
          selectCombo(root, match.value);
        } else {
          closeCombo(root);
          resetComboText(root);
        }
      }
    }, 120);
  });
  list.addEventListener("mousedown", (event) => {
    event.preventDefault();
    const option = event.target.closest("[data-value]");
    if (option) selectCombo(root, option.dataset.value);
  });
  toggle.addEventListener("click", (event) => {
    event.preventDefault();
    if (root.classList.contains("open")) closeCombo(root);
    else {
      input.focus();
      openCombo(root);
      renderCombo(root, "");
    }
  });
}

function initCombos() {
  buildCombo("#combo-uf", "Todas");
  buildCombo("#combo-cidade", "Todas");
  buildCombo("#combo-bairro", "Todos");
  document.addEventListener("click", (event) => {
    document.querySelectorAll("[data-combo]").forEach((root) => {
      if (!root.contains(event.target)) {
        closeCombo(root);
        resetComboText(root);
      }
    });
  });
}

function canonicalOption(values, preferred) {
  if (!preferred || preferred === "all") return "all";
  if (values.includes(preferred)) return preferred;
  const wanted = normText(preferred);
  return values.find((value) => normText(value) === wanted) || "all";
}

function populateUfs(preferred = state.filters.uf, values = null) {
  const meta = state.meta;
  if (!meta) return;
  const list = Array.isArray(values) ? values : (meta.ufs || []);
  const current = canonicalOption(list, preferred);
  comboSet("#combo-uf", list, current, "Todas");
  state.filters.uf = comboValue("#combo-uf");
}

function populateCities(preferred = state.filters.cidade, values = null) {
  const meta = state.meta;
  if (!meta) return;
  const uf = comboValue("#combo-uf");
  const fallback = uf === "all"
    ? uniqueSorted(Object.values(meta.cidades || {}).flat())
    : (meta.cidades?.[uf] || []);
  const cities = Array.isArray(values) ? values : fallback;
  const current = canonicalOption(cities, preferred);
  comboSet("#combo-cidade", cities, current, "Todas");
  state.filters.cidade = comboValue("#combo-cidade");
}

function populateBairros(preferred = state.filters.bairro, values = null) {
  const meta = state.meta;
  if (!meta) return;
  const uf = comboValue("#combo-uf");
  const cidade = comboValue("#combo-cidade");
  if (cidade === "all") {
    comboSetDisabled("#combo-bairro", true);
    state.filters.bairro = "all";
    return;
  }
  let fallback;
  if (uf === "all") {
    fallback = uniqueSorted(
      Object.entries(meta.bairros || {})
        .filter(([key]) => key.endsWith(`|${cidade}`))
        .flatMap(([, list]) => list)
    );
  } else {
    fallback = meta.bairros?.[`${uf}|${cidade}`] || [];
  }
  const bairros = Array.isArray(values) ? values : fallback;
  const current = canonicalOption(bairros, preferred);
  comboSetDisabled("#combo-bairro", false);
  comboSet("#combo-bairro", bairros, current, "Todos");
  state.filters.bairro = comboValue("#combo-bairro");
}

function populateModalidades(preferred = state.filters.modalidade, values = null) {
  const fallback = state.meta?.modalidades || [];
  const modalidades = Array.isArray(values) ? values : fallback;
  const select = $("#f-modalidade");
  select.innerHTML = [`<option value="all">Todas</option>`]
    .concat(modalidades.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`))
    .join("");
  const current = canonicalOption(modalidades, preferred);
  select.value = current;
  state.filters.modalidade = current;
}

function populateFontes(preferred = state.filters.fonte) {
  const fontes = state.meta?.fontes || [];
  const select = $("#f-fonte");
  select.innerHTML = [`<option value="all">Todas</option>`]
    .concat(
      fontes.map(
        (item) =>
          `<option value="${escapeHtml(item.id)}">${escapeHtml(item.nome)} (${Number(item.count).toLocaleString("pt-BR")})</option>`
      )
    )
    .join("");
  select.value = fontes.some((item) => item.id === preferred) ? preferred : "all";
  state.filters.fonte = select.value;
}

function readFilters() {
  return {
    uf: comboValue("#combo-uf"),
    cidade: comboValue("#combo-cidade"),
    bairro: comboValue("#combo-bairro"),
    preco_min: 0,
    preco_max: numberOr($("#f-preco-max").value, DEFAULTS.preco_max),
    desconto_min: numberOr($("#f-desconto-min").value, DEFAULTS.desconto_min),
    lucro_min: numberOr($("#f-lucro-min").value, DEFAULTS.lucro_min),
    financiamento: $("#f-financiamento").value,
    modalidade: $("#f-modalidade").value,
    fonte: $("#f-fonte").value,
    q: $("#f-q").value.trim(),
    bbox: state.mapFilter ? state.bbox : "",
    aplicar_exclusoes: $("#f-exclusoes").checked,
    sort: $("#f-sort").value,
  };
}

function applyFiltersToInputs(filters) {
  populateUfs(filters.uf);
  populateCities(filters.cidade);
  populateBairros(filters.bairro);
  populateModalidades(filters.modalidade);
  populateFontes(filters.fonte);
  $("#f-preco-max").value = filters.preco_max ? filters.preco_max : "";
  $("#f-desconto-min").value = filters.desconto_min ? filters.desconto_min : "";
  $("#f-lucro-min").value = filters.lucro_min ? filters.lucro_min : "";
  $("#f-financiamento").value = ["all", "sim", "nao"].includes(filters.financiamento)
    ? filters.financiamento
    : "all";
  $("#f-q").value = filters.q;
  $("#f-exclusoes").checked = filters.aplicar_exclusoes;
  $("#f-sort").value = filters.sort;
  if (!$("#f-sort").value) $("#f-sort").value = DEFAULTS.sort;
  refreshFilterUI();
}

/* --------------------------------------------------------------------------
 * Facetas calculadas no navegador (mesma semântica de /api/facets).
 * ------------------------------------------------------------------------ */

function scheduleFacets() {
  clearTimeout(state.facetsTimer);
  state.facetsTimer = setTimeout(refreshFacets, 120);
}

function refreshFacets() {
  if (!state.meta || !state.allItems.length || state.facetsApplying) return;
  state.facetsApplying = true;
  try {
    const filters = readFilters();
    const applyExclusions = filters.aplicar_exclusoes;
    const locationParams = { ...filters, uf: "all", cidade: "all", bairro: "all" };
    const locationItems = filterItems(state.allItems, locationParams, applyExclusions);
    const ufs = uniqueSorted(locationItems.map((item) => item.uf));
    const selectedUf = filters.uf;
    const cityItems = selectedUf.toLowerCase() === "all"
      ? locationItems
      : locationItems.filter((item) => normText(item.uf) === normText(selectedUf));
    const cidades = uniqueSorted(cityItems.map((item) => item.cidade));
    const bairros = filters.cidade.toLowerCase() === "all"
      ? []
      : uniqueSorted(
          cityItems
            .filter((item) => normText(item.cidade) === normText(filters.cidade))
            .map((item) => item.bairro)
        );
    const modalityParams = { ...filters, modalidade: "all" };
    const modalityItems = filterItems(state.allItems, modalityParams, applyExclusions);
    const modalidades = uniqueSorted(modalityItems.map((item) => item.modalidade));
    state.facets = {
      ufs,
      cidades,
      bairros,
      modalidades,
      total: locationItems.length,
    };
    applyFacets();
  } finally {
    state.facetsApplying = false;
  }
}

function applyFacets() {
  const facets = state.facets;
  if (!facets) return;
  const before = {
    uf: comboValue("#combo-uf"),
    cidade: comboValue("#combo-cidade"),
    bairro: comboValue("#combo-bairro"),
    modalidade: $("#f-modalidade").value,
  };
  populateUfs(before.uf, facets.ufs);
  populateCities(before.cidade, facets.cidades);
  populateBairros(before.bairro, facets.bairros);
  populateModalidades(before.modalidade, facets.modalidades);
  const after = {
    uf: comboValue("#combo-uf"),
    cidade: comboValue("#combo-cidade"),
    bairro: comboValue("#combo-bairro"),
    modalidade: $("#f-modalidade").value,
  };
  const changed = Object.keys(before).some((key) => before[key] !== after[key]);
  if (changed) fetchProperties();
}

/* --------------------------------------------------------------------------
 * Carregamento dos dados estáticos
 * ------------------------------------------------------------------------ */

function setDataStatus(text) {
  const element = $("#data-meta");
  if (element) element.textContent = text;
}

function setLoadingStatus(text) {
  const element = $("#loading-status");
  if (!element) return;
  element.classList.remove("fade-out");
  element.textContent = text;
}

function finishLoading() {
  document.body.classList.remove("is-loading");
  const status = $("#loading-status");
  if (status) {
    status.classList.add("fade-out");
    setTimeout(() => {
      if (!status.classList.contains("fade-out")) return;
      status.textContent = "";
      status.classList.remove("fade-out");
    }, 500);
  }
  $("#cards")?.setAttribute("aria-busy", "false");
}

async function nextPaint() {
  await new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

async function loadItems(chunks) {
  const paths = (chunks || []).map((name) =>
    name.startsWith("data/") ? name : `${DATA_BASE}${name}`
  );
  if (!paths.length) throw new Error("manifest.json não lista arquivos de dados");
  const payloads = await Promise.all(paths.map(getJSON));
  setLoadingStatus("Processando registros…");
  await nextPaint();
  state.baseItems = payloads.flat();
}

async function loadMeta() {
  setDataStatus("");
  setLoadingStatus("Buscando imóveis…");
  const manifest = await getJSON(`${DATA_BASE}manifest.json`);
  state.manifest = manifest;
  const [meta, update, remoteConfig] = await Promise.all([
    getJSON(`${DATA_BASE}meta.json`),
    getJSON(`${DATA_BASE}ultima_atualizacao.json`).catch(() => null),
    getJSON(`${DATA_BASE}config.json`).catch(() => null),
  ]);
  state.meta = meta;
  state.meta.update = update || {};
  state.remoteConfig = remoteConfig || {
    settings: meta.settings || {},
    exclude_ids: [],
    exclude_locations: [],
    market_values: {},
  };
  setLoadingStatus("Buscando imóveis…");
  await loadItems(manifest.chunks || []);
  setLoadingStatus("Processando registros…");
  await nextPaint();
  recomputeAllItems();
  state.dataLoaded = true;
  buildSearchIndex();

  if (!state.initialized) {
    state.filters = filtersFromURL();
    if (!hasURLFilterParams()) {
      state.filters = applyQuickPresetsToFilters(state.filters, loadQuickPresets());
    }
    state.initialized = true;
  }
  applyFiltersToInputs(state.filters);
  if (state.filters.bbox) {
    state.mapFilter = true;
    state.bbox = state.filters.bbox;
    updateMapFilterUI();
    const bounds = boundsFromBbox(state.bbox);
    if (bounds && state.map) state.map.fitBounds(bounds, { padding: [12, 12] });
  } else if (isMobileLayout()) {
    // No mobile a lista abre primeiro; o mapa ainda não tem dimensões visíveis.
    state.mapFilter = false;
    state.bbox = "";
    updateMapFilterUI();
  } else {
    state.mapFilter = true;
    state.bbox = currentMapBbox();
    updateMapFilterUI();
  }
  updateHeader();
  updateUpdateStatus(state.meta.update || {});
  refreshFacets();
}

function updateHeader() {
  const meta = state.meta;
  if (!meta) return;
  const total = Number(meta.total_properties ?? state.baseItems.length);
  const parts = [`${total.toLocaleString("pt-BR")} imóveis`];
  if (meta.generation_date) parts.push(`gerado em ${meta.generation_date}`);
  setDataStatus(parts.join(" · "));
}

function fetchProperties() {
  if (!state.allItems.length && !state.dataLoaded) return;
  state.filters = readFilters();
  refreshFilterUI();
  syncURL(state.filters);
  const filtered = filterItems(
    state.allItems,
    state.filters,
    state.filters.aplicar_exclusoes
  );
  const sorted = sortItems(filtered, state.filters.sort);
  state.total = sorted.length;
  state.items = sorted.slice(0, MAX_ITEMS_VISIVEIS);
  state.truncated = sorted.length > state.items.length;
  state.visible = PAGE_SIZE;
  state.fit = !state.mapFilter && !state.firstFetch;
  state.firstFetch = false;
  renderCards();
  renderMap();
  updateCount();
  updateGeoStatus({ running: false });
}

function updateCount() {
  let text = `${state.total.toLocaleString("pt-BR")} imóveis`;
  if (state.truncated) {
    text += ` (mostrando ${state.items.length.toLocaleString("pt-BR")})`;
  }
  $("#count").textContent = text;
}

/* --------------------------------------------------------------------------
 * Cartões e mapa
 * ------------------------------------------------------------------------ */

function cardHtml(item) {
  const image = imageSrc(item);
  const link = safeUrl(item.link);
  const excluded = item.excluido
    ? `<span class="badge excluded-badge" title="${escapeHtml(item.motivo_exclusao || "Excluído")}">excluído</span>`
    : "";
  const financing = /^sim$/i.test(item.financiamento)
    ? `<span class="status-badge fin">🟢 Financiável</span>`
    : `<span class="status-badge no-fin">🔴 Sem financiamento</span>`;
  const needsValue = item.sem_preco
    ? `<span class="status-badge needs-value">🟡 Requer ajuste de valor</span>`
    : "";
  const adjusted = item.ajustado
    ? `<span class="status-badge custom-value">✏️ Valor personalizado</span>`
    : "";
  const profitClass = item.lucro != null && item.lucro < 0 ? "negative" : "";
  const bankLabel = sourceLabel(item);
  const street = shortText(item.endereco, 160);
  const place = shortText(`${item.bairro || ""} — ${item.cidade || ""}/${item.uf || ""}`, 90);
  const valuation = item.valor_avaliacao == null
    ? `<span class="muted valuation">Avaliação ${escapeHtml(bankLabel)}: sem avaliação</span>`
    : `<span class="muted valuation" title="Valor de avaliação da fonte">Avaliação ${escapeHtml(bankLabel)}: ${formatBRL(item.valor_avaliacao)}</span>`;
  const customValue = item.ajustado && item.valor_ajustado != null
    ? `<div class="custom-value-line">Seu valor de venda: <strong>${formatBRL(item.valor_ajustado)}</strong></div>`
    : "";
  const profit = item.lucro == null
    ? `<div class="profit" title="Lucro não calculado por falta de valor de avaliação">Lucro não calculado (sem avaliação)</div>`
    : `<div class="profit ${profitClass}" title="Lucro estimado ${formatBRL(item.lucro)} (${formatPct(item.lucro_pct)})">Lucro est. ${formatBRL(item.lucro)} (${formatPct(item.lucro_pct)})</div>`;
  return `
    <article class="card ${item.excluido ? "excluded" : ""}" data-id="${escapeHtml(item.id)}">
      <a class="thumb" href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">
        ${image ? `<img src="${escapeHtml(image)}" alt="Imóvel ${escapeHtml(item.id_fonte || item.id)}" loading="lazy" referrerpolicy="no-referrer" data-fallback="${IMAGE_PLACEHOLDER}">` : `<img src="${IMAGE_PLACEHOLDER}" alt="">`}
        <span class="badge">${discountLabel(item)}</span>
        ${excluded}
      </a>
      <div class="card-body">
        <div class="price-row">
          <strong>${escapeHtml(priceLabel(item))}</strong>
          ${valuation}
        </div>
        ${customValue}
        ${profit}
        <div class="addr">
          <span class="addr-street" title="${escapeHtml(street)}">${escapeHtml(street)}</span>
          <span class="addr-place" title="${escapeHtml(place)}">${escapeHtml(place)}</span>
        </div>
        <div class="tags">
          ${sourceBadge(item)}
          <span class="tag">${escapeHtml(item.modalidade || "—")}</span>
          ${financing}
          ${needsValue}
          ${adjusted}
          <span class="tag">ID ${escapeHtml(item.id_fonte || item.id)}</span>
        </div>
        <div class="card-actions">
          <a class="btn small" href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">Ver oferta</a>
          <button class="btn small" type="button" data-action="adjust" data-id="${escapeHtml(item.id)}">Ajustar valor</button>
          <button class="btn small danger" type="button" data-action="exclude" data-id="${escapeHtml(item.id)}">Excluir</button>
        </div>
      </div>
    </article>
  `;
}

function emptyReason() {
  const filters = state.filters || DEFAULTS;
  if (Number(filters.desconto_min) > 0) {
    return `O filtro “Desconto mín.” está em ${formatPct(filters.desconto_min)} e pode estar restringindo demais. Tente reduzi-lo.`;
  }
  if (Number(filters.lucro_min) > 0) {
    return `O filtro “Lucro mín.” está em ${formatBRL(filters.lucro_min)} e pode estar restringindo demais. Tente reduzi-lo.`;
  }
  if (Number(filters.preco_max) > 0) {
    return `O “Preço máx.” de ${formatBRL(filters.preco_max)} pode estar limitando. Tente aumentá-lo.`;
  }
  if (filters.q) {
    return `A busca por “${filters.q}” não retornou imóveis. Tente outro termo.`;
  }
  if (filters.uf !== "all" || filters.cidade !== "all" || filters.bairro !== "all") {
    return "A localização selecionada pode ser restritiva. Tente uma cidade, bairro ou UF mais ampla.";
  }
  if (filters.financiamento !== "all") {
    return "O filtro de financiamento pode estar restringindo. Tente a opção “Todos”.";
  }
  if (filters.modalidade !== "all") {
    return "A modalidade selecionada pode estar restringindo. Tente a opção “Todas”.";
  }
  if (filters.fonte !== "all") {
    return "A fonte selecionada pode estar restringindo. Tente a opção “Todas”.";
  }
  if (filters.bbox) {
    return "A área visível do mapa pode não ter imóveis. Use “Limpar área” ou mova o mapa.";
  }
  if (filters.aplicar_exclusoes) {
    return "As exclusões locais podem estar removendo os resultados. Desative “Aplicar exclusões” para conferir.";
  }
  return "Nenhum imóvel atende à combinação atual de filtros.";
}

function renderEmptyState() {
  const empty = $("#empty");
  if (!empty) return;
  $("#empty-title").textContent = "Nenhum imóvel encontrado";
  $("#empty-reason").textContent = emptyReason();
  $("#empty .empty-actions")?.classList.remove("hidden");
  $("#empty").classList.remove("hidden");
}

function renderEmptyError(message) {
  const empty = $("#empty");
  if (!empty) return;
  $("#empty-title").textContent = "Não foi possível carregar os dados";
  $("#empty-reason").textContent = message;
  $("#empty .empty-actions")?.classList.add("hidden");
  empty.classList.remove("hidden");
}

function resetAllFilters() {
  state.filters = { ...DEFAULTS };
  state.mapFilter = false;
  state.bbox = "";
  updateMapFilterUI();
  applyFiltersToInputs(state.filters);
  scheduleFetch();
  scheduleFacets();
}

function increasePriceMax() {
  const input = $("#f-preco-max");
  if (!input) return;
  const current = numberOr(input.value, 0);
  const base = current > 0 ? current : Number(state.meta?.preco_max) || 500000;
  const next = Math.ceil(base * 1.2);
  input.value = String(next);
  scheduleFetch();
  scheduleFacets();
  showToast(`Preço máximo aumentado para ${formatBRL(next)}.`);
}

function renderCards() {
  const container = $("#cards");
  const slice = state.items.slice(0, state.visible);
  container.innerHTML = slice.map(cardHtml).join("");
  container.setAttribute("aria-busy", "false");
  const isEmpty = state.dataLoaded && state.items.length === 0;
  if (isEmpty) renderEmptyState();
  else $("#empty").classList.add("hidden");
  $("#btn-more").classList.toggle("hidden", state.visible >= state.items.length);
}

function popupHtml(item) {
  const image = imageSrc(item);
  const link = safeUrl(item.link);
  const profit = item.lucro == null ? "Lucro não calculado" : `Lucro ${formatBRL(item.lucro)}`;
  return `
    <div class="popup">
      ${image ? `<img src="${escapeHtml(image)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-fallback="hide">` : ""}
      <strong>${escapeHtml(priceLabel(item))}</strong>
      <div class="line">${discountLabel(item)} · ${profit}</div>
      <div class="line">${escapeHtml(item.endereco)}<br>${escapeHtml(item.bairro)} — ${escapeHtml(item.cidade)}/${escapeHtml(item.uf)}</div>
      <div class="line">${escapeHtml(sourceLabel(item))} · ${escapeHtml(item.modalidade || "")} · ID ${escapeHtml(item.id_fonte || item.id)}</div>
      ${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">Ver oferta →</a>` : ""}
    </div>
  `;
}

const BRAZIL_VIEW = { center: [-14.235, -51.925], zoom: 4 };

const MAP_TILES = {
  street: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    options: {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    },
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    options: {
      maxZoom: 19,
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
    },
  },
};

function updateMapLayerUI() {
  for (const layer of ["street", "satellite"]) {
    const button = $(`#btn-layer-${layer}`);
    if (!button) continue;
    const active = state.mapLayer === layer;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function setMapLayer(layer) {
  const name = layer === "satellite" ? "satellite" : "street";
  state.mapLayer = name;
  if (state.map && state.tileLayers) {
    for (const [key, tiles] of Object.entries(state.tileLayers)) {
      if (key === name) {
        if (!state.map.hasLayer(tiles)) tiles.addTo(state.map);
      } else if (state.map.hasLayer(tiles)) {
        state.map.removeLayer(tiles);
      }
    }
  }
  writeStoredValue(MAP_LAYER_KEY, name);
  updateMapLayerUI();
}

function currentMapBbox() {
  if (!state.map) return "";
  const bounds = state.map.getBounds();
  return [
    bounds.getSouth().toFixed(6),
    bounds.getWest().toFixed(6),
    bounds.getNorth().toFixed(6),
    bounds.getEast().toFixed(6),
  ].join(",");
}

function boundsFromBbox(value) {
  if (!value) return null;
  const parts = String(value).split(",").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) return null;
  return L.latLngBounds([
    [parts[0], parts[1]],
    [parts[2], parts[3]],
  ]);
}

function updateMapFilterUI() {
  const button = $("#btn-map-filter");
  const clear = $("#btn-map-clear");
  if (!button) return;
  button.classList.toggle("active", state.mapFilter);
  button.textContent = state.mapFilter ? "Filtrando pelo mapa" : "Filtrar pelo mapa";
  button.title = state.mapFilter
    ? "Atualiza automaticamente ao mover ou ampliar o mapa. Clique para desativar."
    : "Filtra os imóveis pela área visível do mapa.";
  clear?.classList.toggle("hidden", !state.mapFilter);
}

function toggleMapFilter(enable) {
  state.mapFilter = enable;
  state.bbox = enable ? currentMapBbox() : "";
  updateMapFilterUI();
  state.fit = false;
  fetchProperties();
  scheduleFacets();
}

function initMap() {
  if (!window.L) {
    $("#map").innerHTML = `<div class="empty">Mapa indisponível (Leaflet não carregou).</div>`;
    return;
  }
  state.map = L.map("map", { zoomControl: true }).setView(BRAZIL_VIEW.center, BRAZIL_VIEW.zoom);
  const storedLayer = readStoredValue(MAP_LAYER_KEY);
  state.mapLayer = storedLayer === "satellite" ? "satellite" : "street";
  state.tileLayers = {
    street: L.tileLayer(MAP_TILES.street.url, MAP_TILES.street.options),
    satellite: L.tileLayer(MAP_TILES.satellite.url, MAP_TILES.satellite.options),
  };
  state.tileLayers[state.mapLayer].addTo(state.map);
  state.cluster = L.markerClusterGroup({
    chunkedLoading: true,
    maxClusterRadius: 55,
    disableClusteringAtZoom: 16,
  });
  state.map.addLayer(state.cluster);
  state.map.on("moveend", () => {
    if (!state.mapFilter) return;
    state.bbox = currentMapBbox();
    scheduleFetch();
    scheduleFacets();
  });
  updateMapFilterUI();
  updateMapLayerUI();
}

function renderMap() {
  if (!state.map || !state.cluster) return;
  state.cluster.clearLayers();
  const points = state.items.filter((item) => item.lat != null && item.lng != null);
  const markers = points.map((item) =>
    L.circleMarker([item.lat, item.lng], {
      radius: 7,
      weight: 1,
      color: "#0b6b57",
      fillColor: "#0e8a70",
      fillOpacity: 0.85,
    }).bindPopup(popupHtml(item))
  );
  state.cluster.addLayers(markers);
  if (state.fit) {
    if (points.length) {
      state.map.fitBounds(
        L.latLngBounds(points.map((item) => [item.lat, item.lng])),
        { padding: [24, 24], maxZoom: 13 }
      );
    } else {
      state.map.setView(BRAZIL_VIEW.center, BRAZIL_VIEW.zoom);
    }
    state.fit = false;
  }
}

function updateGeoStatus() {
  const points = state.items.filter((item) => item.lat != null && item.lng != null).length;
  const total = state.items.length;
  const endereco = state.items.filter((item) => item.geo_precisao === "endereco").length;
  const rua = state.items.filter((item) => item.geo_precisao === "rua").length;
  const bairro = state.items.filter((item) => item.geo_precisao === "bairro").length;
  const cidade = state.items.filter((item) => item.geo_precisao === "cidade").length;
  const estado = state.items.filter((item) => item.geo_precisao === "estado").length;
  let text = `${points.toLocaleString("pt-BR")} de ${total.toLocaleString("pt-BR")} no mapa`;
  const parts = [];
  if (endereco) parts.push(`${endereco.toLocaleString("pt-BR")} endereço`);
  if (rua) parts.push(`${rua.toLocaleString("pt-BR")} rua`);
  if (bairro) parts.push(`${bairro.toLocaleString("pt-BR")} bairro`);
  if (cidade) parts.push(`${cidade.toLocaleString("pt-BR")} cidade`);
  if (estado) parts.push(`${estado.toLocaleString("pt-BR")} estado`);
  if (parts.length) text += ` (${parts.join(", ")})`;
  if (total && points < total) text += " · pontos aproximados";
  $("#geo-status").textContent = text;
}

function updateUpdateStatus(status) {
  const element = $("#update-status");
  if (!element) return;
  const when = status?.data_atualizacao || status?.last_success;
  if (status?.last_error && !when) {
    element.textContent = `Última atualização falhou: ${status.last_error}`;
    return;
  }
  if (when) {
    const date = new Date(when);
    element.textContent = Number.isNaN(date.getTime())
      ? `Atualizado ${when}`
      : `Atualizado ${date.toLocaleString("pt-BR")}`;
  } else {
    element.textContent = "Ainda não atualizado";
  }
  const failures = Object.values(status?.fontes || {}).filter((source) => source.last_error);
  if (failures.length) {
    element.textContent += ` · falha em ${failures.map((source) => source.nome || source.source).join(", ")}`;
  }
}

/* --------------------------------------------------------------------------
 * Ajustes locais: valor de venda e exclusão
 * ------------------------------------------------------------------------ */

function parseMoneyInput(value) {
  let text = String(value ?? "").replace(/R\$/gi, "").replace(/\s/g, "");
  if (!text) return null;
  if (text.includes(",")) {
    text = text.replace(/\./g, "").replace(",", ".");
  } else if ((text.match(/\./g) || []).length === 1 && text.split(".")[1].length === 3) {
    text = text.replace(".", "");
  }
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function formattedInputValue(value) {
  return Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
}

let adjustTargetId = null;

function adjustValue(id) {
  const item = state.allItems.find((entry) => entry.id === id);
  const dialog = $("#adjust-dialog");
  if (!item || !dialog) return;
  adjustTargetId = id;
  $("#adjust-price").textContent = priceLabel(item);
  $("#adjust-valuation-label").textContent = `Avaliação ${sourceLabel(item)}`;
  $("#adjust-valuation").textContent = item.valor_avaliacao == null
    ? "sem avaliação"
    : formatBRL(item.valor_avaliacao);
  const input = $("#adjust-value");
  input.value = item.ajustado && item.valor_ajustado != null
    ? formattedInputValue(item.valor_ajustado)
    : "";
  $("#adjust-error").textContent = "";
  $("#adjust-error").hidden = true;
  $("#btn-adjust-remove").classList.toggle("hidden", !item.ajustado);
  dialog.showModal();
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

function closeAdjustDialog() {
  adjustTargetId = null;
  const dialog = $("#adjust-dialog");
  if (dialog?.open) dialog.close();
}

function saveAdjustment(event) {
  event.preventDefault();
  if (!adjustTargetId) return;
  const input = $("#adjust-value");
  const error = $("#adjust-error");
  const value = parseMoneyInput(input.value);
  if (value === null || value <= 0) {
    error.textContent = "Informe um valor maior que zero.";
    error.hidden = false;
    input.focus();
    return;
  }
  state.local.marketValues[adjustTargetId] = round2(value);
  saveLocalOverrides();
  recomputeAllItems();
  adjustTargetId = null;
  $("#adjust-dialog").close();
  refreshFacets();
  fetchProperties();
  showToast("Valor ajustado neste navegador.");
}

function removeAdjustment() {
  if (!adjustTargetId) return;
  state.local.marketValues[adjustTargetId] = null;
  saveLocalOverrides();
  recomputeAllItems();
  adjustTargetId = null;
  $("#adjust-dialog").close();
  refreshFacets();
  fetchProperties();
  showToast("Ajuste removido neste navegador.");
}

let confirmResolver = null;

function askConfirm(message, confirmLabel = "Sim") {
  const dialog = $("#confirm-dialog");
  if (!dialog || typeof dialog.showModal !== "function") {
    return Promise.resolve(window.confirm(message));
  }
  $("#confirm-message").textContent = message;
  $("#btn-confirm-ok").textContent = confirmLabel;
  return new Promise((resolve) => {
    confirmResolver = resolve;
    dialog.showModal();
  });
}

function resolveConfirm(value) {
  const dialog = $("#confirm-dialog");
  const resolver = confirmResolver;
  confirmResolver = null;
  if (dialog?.open) dialog.close();
  if (resolver) resolver(value);
}

async function excludeItem(id) {
  const confirmed = await askConfirm("Remover este imóvel da sua lista local?", "Sim");
  if (!confirmed) return;
  const hadExcluded = Boolean(state.local.excludedIds[id]);
  const hadUnexcluded = Boolean(state.local.unexcludedIds[id]);
  state.local.excludedIds[id] = true;
  delete state.local.unexcludedIds[id];
  saveLocalOverrides();
  recomputeAllItems();
  refreshFacets();
  fetchProperties();
  showToast("Imóvel removido", {
    actionLabel: "Desfazer",
    duration: 5000,
    onAction: () => {
      if (hadExcluded) state.local.excludedIds[id] = true;
      else delete state.local.excludedIds[id];
      if (hadUnexcluded) state.local.unexcludedIds[id] = true;
      else delete state.local.unexcludedIds[id];
      saveLocalOverrides();
      recomputeAllItems();
      refreshFacets();
      fetchProperties();
      showToast("Exclusão desfeita.");
    },
  });
}

/* --------------------------------------------------------------------------
 * Caixa de configurações (overrides locais + exportação para o repositório)
 * ------------------------------------------------------------------------ */

function parseLocations(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(",").map((part) => part.trim());
      if (parts.length === 1) return { cidade: parts[0], bairro: "all", endereco: "all" };
      if (parts.length === 2) return { cidade: parts[0], bairro: parts[1], endereco: "all" };
      return { cidade: parts[0], bairro: parts[1], endereco: parts.slice(2).join(",") };
    });
}

function parseMarketValues(text) {
  const values = {};
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const comma = trimmed.indexOf(",");
    if (comma < 0) continue;
    const id = trimmed.slice(0, comma).trim();
    const value = parseMoneyInput(trimmed.slice(comma + 1).trim());
    if (id && value !== null) values[id] = value;
  }
  return values;
}

function inputNumber(value) {
  return String(Math.round((Number(value) || 0) * 100) / 100);
}

function syncCustoFixoInput() {
  const percentual = $("#cfg-custo-modo").value === "percentual";
  const input = $("#cfg-custo-fixo");
  input.step = percentual ? "0.01" : "1";
  input.placeholder = percentual ? "Ex.: 5" : "Ex.: 40000";
}

function diffSettings(settings, baked) {
  const keys = ["taxa_venda", "custo_fixo", "custo_fixo_modo", "fator_preco"];
  const diff = {};
  let changed = false;
  for (const key of keys) {
    const a = settings[key];
    const b = baked?.[key];
    if (String(a) !== String(b)) {
      diff[key] = a;
      changed = true;
    }
  }
  return changed ? diff : null;
}

async function openConfig() {
  const dialog = $("#config-dialog");
  try {
    if (!state.remoteConfig) {
      state.remoteConfig = await getJSON(`${DATA_BASE}config.json`).catch(() => ({
        settings: state.meta?.settings || {},
        exclude_ids: [],
        exclude_locations: [],
        market_values: {},
      }));
    }
    const effective = buildEffectiveConfig();
    $("#cfg-ids").value = effective.exclude_ids.join("\n");
    $("#cfg-locations").value = effective.exclude_locations
      .map((location) => `${location.cidade},${location.bairro},${location.endereco}`)
      .join("\n");
    $("#cfg-market").value = Object.entries(effective.market_values)
      .map(([id, value]) => `${id},${value}`)
      .join("\n");
    const settings = effective.settings || {};
    $("#cfg-taxa-venda").value = inputNumber((Number(settings.taxa_venda ?? 0.06)) * 100);
    $("#cfg-custo-modo").value = settings.custo_fixo_modo === "percentual" ? "percentual" : "fixo";
    $("#cfg-custo-fixo").value = inputNumber(settings.custo_fixo ?? 40000);
    $("#cfg-fator-preco").value = inputNumber(((Number(settings.fator_preco ?? 1.05)) - 1) * 100);
    syncCustoFixoInput();
    $("#config-msg").textContent = "";
    dialog.showModal();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveConfig(event) {
  event.preventDefault();
  const taxaPct = Number($("#cfg-taxa-venda").value);
  const custo = Number($("#cfg-custo-fixo").value);
  const fatorPct = Number($("#cfg-fator-preco").value);
  if (
    !Number.isFinite(taxaPct) || taxaPct < 0 || taxaPct > 100 ||
    !Number.isFinite(custo) || custo < 0 ||
    !Number.isFinite(fatorPct) || fatorPct < 0
  ) {
    $("#config-msg").textContent = "Preencha os custos com valores válidos.";
    return;
  }
  const settings = {
    taxa_venda: round2(taxaPct) / 100,
    custo_fixo: custo,
    custo_fixo_modo: $("#cfg-custo-modo").value,
    fator_preco: 1 + round2(fatorPct) / 100,
  };
  const baked = state.remoteConfig || {};
  const bakedIds = new Set(baked.exclude_ids || []);
  const textIds = new Set(
    $("#cfg-ids").value.split("\n").map((line) => line.trim()).filter(Boolean)
  );
  const excludedIds = {};
  const unexcludedIds = {};
  for (const id of textIds) if (!bakedIds.has(id)) excludedIds[id] = true;
  for (const id of bakedIds) if (!textIds.has(id)) unexcludedIds[id] = true;

  const bakedLocations = baked.exclude_locations || [];
  const bakedKeys = new Set(bakedLocations.map(locationKey));
  const textLocations = parseLocations($("#cfg-locations").value);
  const textKeys = new Set(textLocations.map(locationKey));
  const excludeLocations = textLocations.filter(
    (location) => !bakedKeys.has(locationKey(location))
  );
  const removedLocations = bakedLocations
    .filter((location) => !textKeys.has(locationKey(location)))
    .map(locationKey);

  const bakedMarket = baked.market_values || {};
  const textMarket = parseMarketValues($("#cfg-market").value);
  const marketValues = {};
  const marketIds = new Set([...Object.keys(bakedMarket), ...Object.keys(textMarket)]);
  for (const id of marketIds) {
    if (Object.prototype.hasOwnProperty.call(textMarket, id)) {
      if (!Object.prototype.hasOwnProperty.call(bakedMarket, id) || Number(bakedMarket[id]) !== Number(textMarket[id])) {
        marketValues[id] = Number(textMarket[id]);
      }
    } else if (Object.prototype.hasOwnProperty.call(bakedMarket, id)) {
      marketValues[id] = null;
    }
  }

  state.local = {
    marketValues,
    excludedIds,
    unexcludedIds,
    excludeLocations,
    removedLocations,
    settings: diffSettings(settings, baked.settings),
  };
  saveLocalOverrides();
  recomputeAllItems();
  $("#config-dialog").close();
  showToast("Configurações salvas localmente");
  refreshFacets();
  fetchProperties();
}

function resetConfig() {
  if (!confirm("Remover todos os ajustes locais deste navegador?")) return;
  state.local = emptyLocal();
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    // ignore
  }
  recomputeAllItems();
  $("#config-dialog").close();
  showToast("Ajustes locais removidos.");
  refreshFacets();
  fetchProperties();
}

function downloadJSON(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportConfig() {
  const payload = {
    _instrucoes:
      "Aplique este arquivo ao repositório com: python scripts/importar_config.py config-local.json",
    ...buildEffectiveConfig(),
  };
  downloadJSON("config-local.json", payload);
  showToast(
    "Arquivo exportado. Rode scripts/importar_config.py para aplicar ao repositório."
  );
}

/* --------------------------------------------------------------------------
 * Eventos e inicialização
 * ------------------------------------------------------------------------ */

let fetchTimer = null;
function scheduleFetch() {
  clearTimeout(fetchTimer);
  fetchTimer = setTimeout(fetchProperties, 200);
}

function bindEvents() {
  // Fallback de imagens sem usar atributos inline (compatível com CSP).
  document.addEventListener(
    "error",
    (event) => {
      const img = event.target;
      if (!(img instanceof HTMLImageElement)) return;
      const fallback = img.dataset.fallback;
      if (!fallback || fallback === "done") return;
      img.dataset.fallback = "done";
      if (fallback === "hide") {
        img.style.display = "none";
      } else {
        img.src = fallback;
      }
    },
    true
  );

  $("#combo-uf").querySelector("[data-combo-value]").addEventListener("change", () => {
    state.filters.cidade = "all";
    state.filters.bairro = "all";
    populateCities("all");
    populateBairros("all");
    scheduleFetch();
    scheduleFacets();
  });
  $("#combo-cidade").querySelector("[data-combo-value]").addEventListener("change", () => {
    state.filters.bairro = "all";
    populateBairros("all");
    scheduleFetch();
    scheduleFacets();
  });
  $("#combo-bairro").querySelector("[data-combo-value]").addEventListener("change", () => {
    scheduleFetch();
    scheduleFacets();
  });
  $("#f-financiamento").addEventListener("change", () => {
    scheduleFetch();
    scheduleFacets();
  });
  $("#f-modalidade").addEventListener("change", () => {
    scheduleFetch();
    scheduleFacets();
  });
  $("#f-fonte").addEventListener("change", () => {
    scheduleFetch();
    scheduleFacets();
  });
  $("#f-sort").addEventListener("change", scheduleFetch);
  for (const selector of ["#f-preco-max", "#f-desconto-min", "#f-lucro-min", "#f-q"]) {
    $(selector).addEventListener("input", () => {
      scheduleFetch();
      scheduleFacets();
    });
  }
  $("#f-exclusoes").addEventListener("change", () => {
    scheduleFetch();
    scheduleFacets();
  });
  $("#btn-reset").addEventListener("click", resetAllFilters);
  $("#btn-empty-reset").addEventListener("click", resetAllFilters);
  $("#btn-empty-price").addEventListener("click", increasePriceMax);
  $("#btn-filters").addEventListener("click", openFiltersDrawer);
  $("#btn-filters-close").addEventListener("click", closeFiltersDrawer);
  $("#filters-backdrop").addEventListener("click", closeFiltersDrawer);
  $("#btn-view-toggle").addEventListener("click", () => {
    setMobileView(state.mobileMapView ? "list" : "map");
  });
  document.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", () => toggleQuickPreset(button.dataset.preset));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("filters-open")) {
      closeFiltersDrawer();
    }
  });
  window.addEventListener("resize", () => {
    if (!isMobileLayout() && document.body.classList.contains("filters-open")) {
      closeFiltersDrawer();
    }
    resizeMobileMap();
  });
  window.visualViewport?.addEventListener("resize", resizeMobileMap);
  $("#btn-layer-street").addEventListener("click", () => setMapLayer("street"));
  $("#btn-layer-satellite").addEventListener("click", () => setMapLayer("satellite"));
  $("#btn-map-filter").addEventListener("click", () => toggleMapFilter(!state.mapFilter));
  $("#btn-map-clear").addEventListener("click", () => toggleMapFilter(false));
  $("#btn-more").addEventListener("click", () => {
    state.visible += PAGE_SIZE;
    renderCards();
  });
  $("#cards").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    if (button.dataset.action === "adjust") adjustValue(button.dataset.id);
    if (button.dataset.action === "exclude") excludeItem(button.dataset.id);
  });
  $("#btn-notice").addEventListener("click", openNotice);
  $("#btn-notice-close").addEventListener("click", acceptNotice);
  $("#btn-notice-decline").addEventListener("click", declineNotice);
  $("#btn-notice-help").addEventListener("click", openHelp);
  $("#btn-help").addEventListener("click", openHelp);
  $("#btn-help-close").addEventListener("click", () => $("#help-dialog").close());
  $("#btn-feedback").addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    openFeedback();
  });
  $("#btn-feedback-close").addEventListener("click", () => $("#feedback-dialog").close());
  $("#btn-share").addEventListener("click", copyShareLink);
  $("#btn-config").addEventListener("click", openConfig);
  $("#btn-config-close").addEventListener("click", () => $("#config-dialog").close());
  $("#btn-config-export").addEventListener("click", exportConfig);
  $("#btn-config-reset").addEventListener("click", resetConfig);
  $("#cfg-custo-modo").addEventListener("change", syncCustoFixoInput);
  $("#config-form").addEventListener("submit", saveConfig);
  $("#adjust-form").addEventListener("submit", saveAdjustment);
  $("#btn-adjust-remove").addEventListener("click", removeAdjustment);
  $("#btn-adjust-cancel").addEventListener("click", closeAdjustDialog);
  $("#adjust-dialog").addEventListener("close", () => {
    adjustTargetId = null;
  });
  $("#adjust-dialog").addEventListener("click", (event) => {
    if (event.target === $("#adjust-dialog")) closeAdjustDialog();
  });
  $("#btn-confirm-ok").addEventListener("click", () => resolveConfirm(true));
  $("#btn-confirm-cancel").addEventListener("click", () => resolveConfirm(false));
  $("#confirm-dialog").addEventListener("cancel", (event) => {
    event.preventDefault();
    resolveConfirm(false);
  });
  $("#confirm-dialog").addEventListener("close", () => {
    if (confirmResolver) {
      const resolver = confirmResolver;
      confirmResolver = null;
      resolver(false);
    }
  });
  $("#confirm-dialog").addEventListener("click", (event) => {
    if (event.target === $("#confirm-dialog")) resolveConfirm(false);
  });
}

async function init() {
  bindTooltips();
  initMap();
  state.mapFilter = !isMobileLayout();
  state.bbox = state.mapFilter ? currentMapBbox() : "";
  updateMapFilterUI();
  initCombos();
  bindEvents();
  initSearchAutocomplete();
  showNoticeIfNeeded();
  window.__loadGTM?.();
  try {
    await loadMeta();
    await fetchProperties();
  } catch (error) {
    setDataStatus("Falha ao carregar os dados.");
    $("#cards").innerHTML = "";
    renderEmptyError(`Não foi possível carregar os dados: ${error.message}`);
    showToast(error.message, true);
  } finally {
    finishLoading();
  }
}

init();
