const $ = (selector) => document.querySelector(selector);

const DATA_BASE = "data/";
const MAX_ITEMS_VISIVEIS = 5000;
const PAGE_SIZE = 60;
const IMAGE_PLACEHOLDER = "static/placeholder.svg";
const STORAGE_KEY = "imoveis-radar-static:overrides:v1";
const NOTICE_KEY = "imoveis-radar-static:notice:v1";

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

function loadLocalOverrides() {
  const base = emptyLocal();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return base;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return base;
    return {
      marketValues: parsed.marketValues || {},
      excludedIds: parsed.excludedIds || {},
      unexcludedIds: parsed.unexcludedIds || {},
      excludeLocations: Array.isArray(parsed.excludeLocations)
        ? parsed.excludeLocations
        : [],
      removedLocations: Array.isArray(parsed.removedLocations)
        ? parsed.removedLocations
        : [],
      settings: parsed.settings || null,
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
  fit: true,
  initialized: false,
  facets: null,
  facetsTimer: null,
  mapFilter: false,
  bbox: "",
  firstFetch: true,
  facetsApplying: false,
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

function safeUrl(value) {
  const text = String(value || "").trim();
  return /^https?:\/\//i.test(text) ? text : "";
}

function imageSrc(item) {
  const url = safeUrl(item.imagem);
  if (!url) return "";
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

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 3500);
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
  if (dialog && !dialog.open) dialog.showModal();
}

function acceptNotice() {
  try {
    window.localStorage.setItem(NOTICE_KEY, "1");
  } catch (error) {
    // Sem localStorage, o aviso volta na próxima visita.
  }
  const dialog = $("#notice-dialog");
  if (dialog) dialog.close();
}

function showNoticeIfNeeded() {
  if (!noticeSeen()) openNotice();
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

function populateUfs(preferred = state.filters.uf, values = null) {
  const meta = state.meta;
  if (!meta) return;
  const list = Array.isArray(values) ? values : (meta.ufs || []);
  let current = preferred;
  if (current !== "all" && !list.includes(current)) current = "all";
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
  comboSet("#combo-cidade", cities, preferred, "Todas");
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
  comboSetDisabled("#combo-bairro", false);
  comboSet("#combo-bairro", bairros, preferred, "Todos");
  state.filters.bairro = comboValue("#combo-bairro");
}

function populateModalidades(preferred = state.filters.modalidade, values = null) {
  const fallback = state.meta?.modalidades || [];
  const modalidades = Array.isArray(values) ? values : fallback;
  const select = $("#f-modalidade");
  select.innerHTML = [`<option value="all">Todas</option>`]
    .concat(modalidades.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`))
    .join("");
  select.value = modalidades.includes(preferred) ? preferred : "all";
  state.filters.modalidade = select.value;
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

async function loadItems(chunks) {
  const paths = (chunks || []).map((name) =>
    name.startsWith("data/") ? name : `${DATA_BASE}${name}`
  );
  if (!paths.length) throw new Error("manifest.json não lista arquivos de dados");
  const payloads = await Promise.all(paths.map(getJSON));
  state.baseItems = payloads.flat();
}

async function loadMeta() {
  setDataStatus("Carregando dados…");
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
  await loadItems(manifest.chunks || []);
  recomputeAllItems();

  if (!state.initialized) {
    state.filters = filtersFromURL();
    state.initialized = true;
  }
  applyFiltersToInputs(state.filters);
  if (state.filters.bbox) {
    state.mapFilter = true;
    state.bbox = state.filters.bbox;
    updateMapFilterUI();
    const bounds = boundsFromBbox(state.bbox);
    if (bounds && state.map) state.map.fitBounds(bounds, { padding: [12, 12] });
  }
  updateHeader();
  updateUpdateStatus(state.meta.update || {});
  setGeocodeRunning(false);
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
  if (!state.allItems.length) return;
  state.filters = readFilters();
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
  const adjusted = item.ajustado
    ? `<span class="badge adjusted" title="Valor de venda ajustado manualmente">ajustado</span>`
    : "";
  const excluded = item.excluido
    ? `<span class="badge excluded-badge" title="${escapeHtml(item.motivo_exclusao || "Excluído")}">excluído</span>`
    : "";
  const financing = /^sim$/i.test(item.financiamento)
    ? `<span class="tag fin">Financiável</span>`
    : `<span class="tag">Sem financiamento</span>`;
  const profitClass = item.lucro != null && item.lucro < 0 ? "negative" : "";
  const valuation = item.valor_ajustado == null
    ? `<span class="muted">sem avaliação</span>`
    : `<span class="muted" title="${item.ajustado ? "Valor de venda ajustado" : "Valor de avaliação"}">${formatBRL(item.valor_ajustado)}</span>`;
  const profit = item.lucro == null
    ? `<div class="profit">Lucro não calculado (sem valor de avaliação)</div>`
    : `<div class="profit ${profitClass}">Lucro est. ${formatBRL(item.lucro)} (${formatPct(item.lucro_pct)})</div>`;
  return `
    <article class="card ${item.excluido ? "excluded" : ""}" data-id="${escapeHtml(item.id)}">
      <a class="thumb" href="${link}" target="_blank" rel="noopener noreferrer">
        ${image ? `<img src="${image}" alt="Imóvel ${escapeHtml(item.id_fonte || item.id)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src='${IMAGE_PLACEHOLDER}'">` : `<img src="${IMAGE_PLACEHOLDER}" alt="">`}
        <span class="badge">${discountLabel(item)}</span>
        ${adjusted}
        ${excluded}
      </a>
      <div class="card-body">
        <div class="price-row">
          <strong>${priceLabel(item)}</strong>
          ${valuation}
        </div>
        ${profit}
        <div class="addr">${escapeHtml(item.endereco)}<br>${escapeHtml(item.bairro)} — ${escapeHtml(item.cidade)}/${escapeHtml(item.uf)}</div>
        <div class="tags">
          ${sourceBadge(item)}
          <span class="tag">${escapeHtml(item.modalidade || "—")}</span>
          ${financing}
          <span class="tag">ID ${escapeHtml(item.id_fonte || item.id)}</span>
        </div>
        <div class="card-actions">
          <a class="btn small" href="${link}" target="_blank" rel="noopener noreferrer">Ver oferta</a>
          <button class="btn small" type="button" data-action="adjust" data-id="${escapeHtml(item.id)}">Ajustar valor</button>
          <button class="btn small danger" type="button" data-action="exclude" data-id="${escapeHtml(item.id)}">Excluir</button>
        </div>
      </div>
    </article>
  `;
}

function renderCards() {
  const container = $("#cards");
  const slice = state.items.slice(0, state.visible);
  container.innerHTML = slice.map(cardHtml).join("");
  $("#empty").classList.toggle("hidden", state.items.length > 0);
  $("#btn-more").classList.toggle("hidden", state.visible >= state.items.length);
}

function popupHtml(item) {
  const image = imageSrc(item);
  const link = safeUrl(item.link);
  const profit = item.lucro == null ? "Lucro não calculado" : `Lucro ${formatBRL(item.lucro)}`;
  return `
    <div class="popup">
      ${image ? `<img src="${image}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'">` : ""}
      <strong>${priceLabel(item)}</strong>
      <div class="line">${discountLabel(item)} · ${profit}</div>
      <div class="line">${escapeHtml(item.endereco)}<br>${escapeHtml(item.bairro)} — ${escapeHtml(item.cidade)}/${escapeHtml(item.uf)}</div>
      <div class="line">${escapeHtml(sourceLabel(item))} · ${escapeHtml(item.modalidade || "")} · ID ${escapeHtml(item.id_fonte || item.id)}</div>
      ${link ? `<a href="${link}" target="_blank" rel="noopener noreferrer">Ver oferta →</a>` : ""}
    </div>
  `;
}

const BRAZIL_VIEW = { center: [-14.235, -51.925], zoom: 4 };

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
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(state.map);
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

function updateGeoStatus(job) {
  const points = state.items.filter((item) => item.lat != null && item.lng != null).length;
  const total = state.items.length;
  const bairro = state.items.filter((item) => item.geo_precisao === "bairro").length;
  const cidade = state.items.filter((item) => item.geo_precisao === "cidade").length;
  const estado = state.items.filter((item) => item.geo_precisao === "estado").length;
  let text = `${points.toLocaleString("pt-BR")} de ${total.toLocaleString("pt-BR")} no mapa`;
  if (job && job.running) {
    text = `Geocodificando ${job.done || 0}/${job.total || 0}…`;
  } else {
    const parts = [];
    if (bairro) parts.push(`${bairro.toLocaleString("pt-BR")} bairro`);
    if (cidade) parts.push(`${cidade.toLocaleString("pt-BR")} cidade`);
    if (estado) parts.push(`${estado.toLocaleString("pt-BR")} estado`);
    if (parts.length) text += ` (${parts.join(", ")})`;
  }
  $("#geo-status").textContent = text;
}

function setGeocodeRunning(running) {
  $("#btn-geocode").disabled = Boolean(running);
  $("#btn-geocode-all").disabled = Boolean(running);
  $("#btn-geocode-cancel").classList.toggle("hidden", !running);
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

function startGeocode(scope = "filtered") {
  showToast(
    "A geocodificação é feita pelo script Python durante a atualização automática."
  );
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

function adjustValue(id) {
  const item = state.allItems.find((entry) => entry.id === id);
  if (!item) return;
  const current = item.valor_ajustado ?? item.valor_avaliacao ?? item.preco ?? 0;
  const answer = prompt(
    `Valor de venda aproximado para o imóvel ${id}.\nDeixe vazio para remover o ajuste.`,
    String(Math.round(current))
  );
  if (answer === null) return;
  const trimmed = answer.trim();
  if (!trimmed) {
    state.local.marketValues[id] = null;
  } else {
    const value = parseMoneyInput(trimmed);
    if (value === null || value <= 0) {
      showToast("Valor inválido.", true);
      return;
    }
    state.local.marketValues[id] = round2(value);
  }
  saveLocalOverrides();
  recomputeAllItems();
  refreshFacets();
  fetchProperties();
  showToast(trimmed ? "Valor ajustado neste navegador." : "Ajuste removido neste navegador.");
}

function excludeItem(id) {
  if (!confirm(`Excluir o imóvel ${id} da lista neste navegador?`)) return;
  state.local.excludedIds[id] = true;
  delete state.local.unexcludedIds[id];
  saveLocalOverrides();
  recomputeAllItems();
  refreshFacets();
  fetchProperties();
  showToast("Imóvel excluído neste navegador.");
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
  showToast("Configuração salva neste navegador.");
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
  $("#btn-reset").addEventListener("click", () => {
    state.filters = { ...DEFAULTS };
    state.mapFilter = false;
    state.bbox = "";
    updateMapFilterUI();
    applyFiltersToInputs(state.filters);
    scheduleFetch();
    scheduleFacets();
  });
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
  $("#btn-share").addEventListener("click", copyShareLink);
  $("#btn-geocode").addEventListener("click", () => startGeocode("filtered"));
  $("#btn-geocode-all").addEventListener("click", () => startGeocode("all"));
  $("#btn-geocode-cancel").addEventListener("click", () => setGeocodeRunning(false));
  $("#btn-config").addEventListener("click", openConfig);
  $("#btn-config-close").addEventListener("click", () => $("#config-dialog").close());
  $("#btn-config-export").addEventListener("click", exportConfig);
  $("#btn-config-reset").addEventListener("click", resetConfig);
  $("#cfg-custo-modo").addEventListener("change", syncCustoFixoInput);
  $("#config-form").addEventListener("submit", saveConfig);
}

async function init() {
  initMap();
  initCombos();
  bindEvents();
  showNoticeIfNeeded();
  try {
    await loadMeta();
    await fetchProperties();
  } catch (error) {
    setDataStatus("Falha ao carregar os dados.");
    $("#empty").classList.remove("hidden");
    $("#empty").textContent = `Não foi possível carregar os dados: ${error.message}`;
    showToast(error.message, true);
  }
}

init();
