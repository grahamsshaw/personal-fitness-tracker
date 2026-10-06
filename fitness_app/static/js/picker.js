/* Shared exercise picker: search + body-part tabs + multi equipment chips
 * + multi muscle-map taps. One panel, every page that picks exercises.
 *
 * Host page must define:
 *   window.pickerOnPick(exercise)  — {id, name, ...} from /api/exercises
 *   window.pickerOnCustom(name)    — typed name fallback
 * and include the _exercise_picker.html panel plus muscles.js before this.
 */

(function () {
  "use strict";

  // Active filters. equipment/muscles are SETS (multi-select); part single.
  const filters = { q: "", part: "", equipment: new Set(), muscles: new Set() };

  function params() {
    const out = new URLSearchParams();
    if (filters.q) out.set("q", filters.q);
    if (filters.part) out.set("body_part", filters.part);
    filters.equipment.forEach((e) => out.append("equipment", e));
    filters.muscles.forEach((m) => out.append("muscle", m));
    return out.toString();
  }

  function renderResults(exercises) {
    const box = document.getElementById("browse-results");
    if (!box) return;
    box.innerHTML = "";
    if (!exercises.length) {
      box.innerHTML =
        '<p class="text-muted">Nothing matches — loosen a filter or type a name below.</p>';
      return;
    }
    exercises.slice(0, 30).forEach((e) => {
      const row = document.createElement("div");
      row.className = "browse-result";
      const label = document.createElement("span");
      label.textContent = e.name + (e.equipment_label ? ` (${e.equipment_label})` : "");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-small btn-primary";
      btn.textContent = "Add";
      btn.addEventListener("click", () => window.pickerOnPick(e));
      row.appendChild(label);
      row.appendChild(btn);
      box.appendChild(row);
    });
    if (exercises.length > 30) {
      const more = document.createElement("p");
      more.className = "text-muted";
      more.textContent = `Showing 30 of ${exercises.length} — narrow the search.`;
      box.appendChild(more);
    }
  }

  function refresh() {
    fetch("/api/exercises?" + params())
      .then((r) => r.json())
      .then(renderResults)
      .catch(() => {
        const box = document.getElementById("browse-results");
        if (box) box.innerHTML = '<p class="text-muted">Could not load exercises.</p>';
      });
  }

  function renderChips(boxId, items, active, toggle) {
    const box = document.getElementById(boxId);
    if (!box) return;
    box.innerHTML = "";
    items.forEach(([value, label, count]) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip" + (active(value) ? " active" : "");
      btn.textContent = count != null ? `${label} (${count})` : label;
      btn.addEventListener("click", () => {
        toggle(value);
        refresh();
        renderMap();
      });
      box.appendChild(btn);
    });
  }

  function renderParts(parts) {
    renderChips(
      "browse-parts",
      [["", "All", null]].concat(parts.map(([name, count]) => [name, name, count])),
      (v) => filters.part === v,
      (v) => { filters.part = filters.part === v ? "" : v; renderParts(parts); }
    );
  }

  function renderEquip(equipment) {
    const items = [["__any__", "Any", null]].concat(
      equipment.map(([name, count]) => [name, name, count])
    );
    const box = document.getElementById("browse-equip");
    if (!box) return;
    box.innerHTML = "";
    items.forEach(([value, label, count]) => {
      const isAny = value === "__any__";
      const on = isAny ? filters.equipment.size === 0 : filters.equipment.has(value);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip" + (on ? " active" : "");
      btn.textContent = count != null ? `${label} (${count})` : label;
      btn.addEventListener("click", () => {
        if (isAny) filters.equipment.clear();
        else if (filters.equipment.has(value)) filters.equipment.delete(value);
        else filters.equipment.add(value);
        renderEquip(equipment);
        refresh();
      });
      box.appendChild(btn);
    });
  }

  function muscleLabel() {
    const label = document.getElementById("browse-muscle-label");
    if (!label || !window.BodyMap) return;
    const names = window.BodyMap.names;
    if (!filters.muscles.size) {
      label.textContent = "";
      return;
    }
    const shown = [...filters.muscles].map(
      (m) => (m === "full_body" ? "full body" : names[m] || m)
    );
    label.textContent = `Showing: ${shown.join(", ")} — tap again to clear`;
  }

  function renderMap() {
    if (!window.BodyMap) return;
    const highlight = {};
    filters.muscles.forEach((m) => {
      if (m !== "full_body") highlight[m] = 4;
    });
    window.BodyMap.render("browse-map", {
      highlight: highlight,
      interactive: true,
      onSelect: (muscle) => {
        if (filters.muscles.has(muscle)) filters.muscles.delete(muscle);
        else filters.muscles.add(muscle);
        muscleLabel();
        renderMap();
        refresh();
      },
    });
    // Full-body toggle beside the map label (3+ muscles, not a shape).
    let fullBtn = document.getElementById("browse-fullbody");
    if (!fullBtn) {
      fullBtn = document.createElement("button");
      fullBtn.type = "button";
      fullBtn.id = "browse-fullbody";
      fullBtn.className = "btn btn-small btn-secondary";
      fullBtn.textContent = "Full body";
      fullBtn.addEventListener("click", () => {
        if (filters.muscles.has("full_body")) filters.muscles.delete("full_body");
        else filters.muscles.add("full_body");
        muscleLabel();
        refresh();
        renderFullState();
      });
      const label = document.getElementById("browse-muscle-label");
      if (label) label.after(fullBtn);
    }
    renderFullState();
  }

  function renderFullState() {
    const btn = document.getElementById("browse-fullbody");
    if (btn) btn.classList.toggle("active-chip", filters.muscles.has("full_body"));
  }

  function init() {
    if (!document.getElementById("exercise-browser")) return;

    let timer = null;
    const search = document.getElementById("browse-q");
    if (search) {
      search.addEventListener("input", (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          filters.q = e.target.value.trim();
          refresh();
        }, 250);
      });
    }

    const customAdd = document.getElementById("custom-add");
    if (customAdd) {
      customAdd.addEventListener("click", () => {
        const input = document.getElementById("custom-name");
        if (input && input.value.trim() && window.pickerOnCustom) {
          window.pickerOnCustom(input.value.trim());
          input.value = "";
        }
      });
    }

    fetch("/api/exercise-facets")
      .then((r) => r.json())
      .then((facets) => {
        renderParts(facets.body_parts || []);
        renderEquip(facets.equipment || []);
        renderMap();
        refresh();
      })
      .catch(() => {
        renderMap();
        refresh();
      });
  }

  document.addEventListener("DOMContentLoaded", init);
  window.ExercisePicker = { refresh: refresh, filters: filters };
})();
