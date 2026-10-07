/* Appearance: light/dark theme and accent colour.
 *
 * Device-local only (localStorage) — appearance is not account data and this
 * tracker has no accounts, so there is deliberately no server endpoint for
 * it. The inline snippet in base.html applies the stored theme before first
 * paint; this file owns everything after that.
 */

(function () {
  "use strict";

  var THEME_KEY = "ft-theme"; // "light" | "dark" | "auto"
  var ACCENT_KEY = "ft-accent"; // accent name, see ACCENTS

  var ACCENTS = {
    blue: "#2563eb",
    green: "#16a34a",
    orange: "#ea580c",
    purple: "#9333ea",
    rose: "#e11d48",
  };

  function systemDark() {
    return (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }

  function resolveTheme(stored) {
    if (stored === "light" || stored === "dark") return stored;
    return "dark";
  }

  function apply() {
    var stored = null;
    var accent = "blue";
    try {
      stored = localStorage.getItem(THEME_KEY);
      accent = localStorage.getItem(ACCENT_KEY) || "blue";
    } catch (e) {
      /* Private mode etc: fall through to defaults. */
    }
    if (!ACCENTS[accent]) accent = "blue";
    document.documentElement.setAttribute("data-theme", resolveTheme(stored));
    document.documentElement.setAttribute("data-accent", accent);
    document.documentElement.style.setProperty("--primary", ACCENTS[accent]);
  }

  function setTheme(mode) {
    try {
      localStorage.setItem(THEME_KEY, mode);
    } catch (e) {
      /* Non-fatal: the attribute below still applies for this page. */
    }
    document.documentElement.setAttribute("data-theme", resolveTheme(mode));
    syncToggle();
  }

  function setAccent(name) {
    if (!ACCENTS[name]) return;
    try {
      localStorage.setItem(ACCENT_KEY, name);
    } catch (e) {
      /* Non-fatal. */
    }
    document.documentElement.setAttribute("data-accent", name);
    document.documentElement.style.setProperty("--primary", ACCENTS[name]);
    syncSwatches();
  }

  function syncToggle() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    var dark =
      document.documentElement.getAttribute("data-theme") === "dark";
    btn.textContent = dark ? "☾" : "☀";
    btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  }

  function syncSwatches() {
    var current = document.documentElement.getAttribute("data-accent");
    document.querySelectorAll("[data-accent-pick]").forEach(function (el) {
      el.classList.toggle("active", el.getAttribute("data-accent-pick") === current);
    });
  }

  // Apply as early as possible; base.html also runs a smaller inline version
  // of this before first paint to avoid a flash.
  apply();

  document.addEventListener("DOMContentLoaded", function () {
    syncToggle();
    syncSwatches();

    var toggle = document.getElementById("theme-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        var dark =
          document.documentElement.getAttribute("data-theme") === "dark";
        setTheme(dark ? "light" : "dark");
      });
    }

    document.querySelectorAll("[data-accent-pick]").forEach(function (el) {
      el.addEventListener("click", function () {
        setAccent(el.getAttribute("data-accent-pick"));
      });
      el.style.background = ACCENTS[el.getAttribute("data-accent-pick")] || ACCENTS.blue;
    });

    var reset = document.getElementById("theme-auto");
    if (reset) {
      reset.addEventListener("click", function () {
        setTheme("auto");
      });
    }
  });

  window.FitnessTheme = { setTheme: setTheme, setAccent: setAccent, apply: apply };
})();
