/* Body muscle map renderer.
 *
 * Draws clickable front/back SVG figures from body-paths.json geometry,
 * shaded 0-4 per muscle. Written from scratch for this project; only the
 * geometry comes from elsewhere (MIT-licensed, see THIRD-PARTY-NOTICES.md).
 *
 * Usage (stats page):
 *   BodyMap.render("bodymap", { mode: "fatigue", onSelect: showMuscle });
 *
 * Usage (static highlight, e.g. equipment page):
 *   BodyMap.render("equip-map", { highlight: { quadriceps: 3 }, interactive: false });
 */

(function () {
  "use strict";

  const DISPLAY_NAMES = {
    trapezius: "Traps",
    deltoids: "Shoulders",
    chest: "Chest",
    "upper-back": "Upper back",
    serratus: "Serratus",
    biceps: "Biceps",
    triceps: "Triceps",
    forearm: "Forearms",
    abs: "Abs",
    obliques: "Obliques",
    "lower-back": "Lower back",
    gluteal: "Glutes",
    quadriceps: "Quads",
    hamstring: "Hamstrings",
    adductors: "Adductors",
    "hip-flexors": "Hip flexors",
    calves: "Calves",
    tibialis: "Shins",
  };

  // Geometry keys drawn as silhouette only — they carry no training load.
  const INERT = new Set(["head", "hair", "neck", "hands", "feet", "knees", "ankles"]);

  let geometryPromise = null;

  function loadGeometry() {
    if (!geometryPromise) {
      geometryPromise = fetch("/static/map-data/body-paths.json").then((r) => {
        if (!r.ok) throw new Error("body map geometry not found");
        return r.json();
      });
    }
    return geometryPromise;
  }

  function svgForSide(view, levels, interactive, selected, onSelect) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", view.vb);
    svg.classList.add("bodymap-svg");
    svg.setAttribute("role", interactive ? "group" : "img");

    const addPaths = (muscle, paths, inert) => {
      (paths || []).forEach((d, i) => {
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", d);
        if (inert) {
          path.setAttribute("class", "bm-sil");
        } else {
          const level = Math.max(0, Math.min(4, levels[muscle] || 0));
          path.setAttribute("class", "bm-m m" + level + (selected === muscle ? " sel" : ""));
          const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
          title.textContent = DISPLAY_NAMES[muscle] || muscle;
          path.appendChild(title);
          if (interactive && onSelect) {
            path.style.cursor = "pointer";
            path.addEventListener("click", () => onSelect(muscle));
          }
        }
        svg.appendChild(path);
      });
    };

    Object.keys(view.p).forEach((muscle) => {
      addPaths(muscle, view.p[muscle], INERT.has(muscle));
    });
    return svg;
  }

  async function render(containerId, options) {
    const opts = Object.assign(
      { mode: "fatigue", gender: "male", interactive: true, highlight: null, onSelect: null },
      options || {}
    );
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '<p class="text-muted">Loading body map…</p>';

    try {
      const geometry = await loadGeometry();
      let levels = opts.highlight;
      if (!levels) {
        const res = await fetch("/api/charts/muscles?mode=" + encodeURIComponent(opts.mode));
        if (!res.ok) throw new Error("muscle data not available");
        const data = await res.json();
        levels = data.levels || {};
      }
      const person = (geometry && geometry[opts.gender]) || geometry.male;

      container.innerHTML = "";
      const wrap = document.createElement("div");
      wrap.className = "bodymap-figures";

      ["front", "back"].forEach((side) => {
        const figure = document.createElement("figure");
        figure.className = "bodymap-figure";
        const caption = document.createElement("figcaption");
        caption.textContent = side === "front" ? "Front" : "Back";
        figure.appendChild(
          svgForSide(person[side], levels, opts.interactive, opts.selected, opts.onSelect)
        );
        figure.appendChild(caption);
        wrap.appendChild(figure);
      });
      container.appendChild(wrap);
    } catch (err) {
      container.innerHTML = '<p class="text-muted">Body map unavailable.</p>';
    }
  }

  window.BodyMap = { render: render, names: DISPLAY_NAMES };
})();
