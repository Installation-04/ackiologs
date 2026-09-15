/* Minimal, dependency-free i18n: loads a flat/nested JSON dictionary per locale
 * (app/web/static/i18n/<locale>.json) and resolves dot-path keys with {var}
 * interpolation. No CDN dependency, consistent with the rest of this dashboard's
 * "works air-gapped" requirement. */
(() => {
  const SUPPORTED_LOCALES = ["en", "es", "fr", "de", "pt", "zh"];
  const STORAGE_KEY = "ackiologs_lang";
  let translations = {};
  let currentLocale = "en";

  function detectBrowserLocale() {
    const langs = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || "en"];
    for (const l of langs) {
      const base = String(l).split("-")[0].toLowerCase();
      if (SUPPORTED_LOCALES.includes(base)) return base;
    }
    return "en";
  }

  function getStoredLocale() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function setStoredLocale(loc) {
    try {
      localStorage.setItem(STORAGE_KEY, loc);
    } catch (e) {
      /* private browsing / storage disabled — language just won't persist */
    }
  }

  async function loadLocale(loc) {
    const resolved = SUPPORTED_LOCALES.includes(loc) ? loc : "en";
    const res = await fetch(`i18n/${resolved}.json`);
    translations = await res.json();
    currentLocale = resolved;
    document.documentElement.lang = resolved;
    return resolved;
  }

  function t(path, vars) {
    const parts = path.split(".");
    let node = translations;
    for (const p of parts) {
      if (node == null) return path;
      node = node[p];
    }
    if (typeof node !== "string") return path;
    if (!vars) return node;
    return node.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? vars[k] : `{${k}}`));
  }

  function tSetting(settingKey, field) {
    const entry = translations.settingsSchema && translations.settingsSchema.keys && translations.settingsSchema.keys[settingKey];
    return entry ? entry[field] : undefined;
  }

  function tCategory(category) {
    const cats = translations.settingsSchema && translations.settingsSchema.categories;
    return (cats && cats[category]) || category;
  }

  function applyStaticTranslations(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
    });
    scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
    });
  }

  window.AckiologsI18n = {
    SUPPORTED_LOCALES,
    detectBrowserLocale,
    getStoredLocale,
    setStoredLocale,
    loadLocale,
    t,
    tSetting,
    tCategory,
    applyStaticTranslations,
    get locale() {
      return currentLocale;
    },
  };
})();
