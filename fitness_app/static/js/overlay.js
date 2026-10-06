/* Overlay system: modal boxes over the page below.
 *
 * Any page can open inside an overlay via openOverlay(url): the URL loads
 * with ?embed=1 (navigation stripped by base.html) in an iframe, so every
 * existing page works as an overlay with zero backend changes. Overlays
 * nest — an overlay can open another on top — and clicking the backdrop
 * or pressing Escape closes only the topmost, returning to the page below.
 *
 * Links inside an overlayed page navigate inside the overlay, which is
 * what detail-drilling (session -> exercise history) wants. Links with
 * target="_top" or data-top="1" break out to the full page instead.
 */

(function () {
  "use strict";

  var stack = [];

  function current() {
    return stack.length ? stack[stack.length - 1] : null;
  }

  function withEmbed(url) {
    try {
      var parsed = new URL(url, window.location.origin);
      parsed.searchParams.set("embed", "1");
      return parsed.toString();
    } catch (e) {
      return url;
    }
  }

  function openOverlay(url) {
    var backdrop = document.createElement("div");
    backdrop.className = "overlay-backdrop";

    var box = document.createElement("div");
    box.className = "overlay-box";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "overlay-close";
    closeBtn.setAttribute("aria-label", "Close");
    closeBtn.textContent = "×";
    closeBtn.addEventListener("click", closeOverlay);

    var frame = document.createElement("iframe");
    frame.className = "overlay-frame";
    frame.setAttribute("title", "Details");
    frame.src = withEmbed(url);

    box.appendChild(closeBtn);
    box.appendChild(frame);
    backdrop.appendChild(box);
    // Clicking the backdrop (not the box) returns to the page below.
    backdrop.addEventListener("mousedown", function (e) {
      if (e.target === backdrop) closeOverlay();
    });
    document.body.appendChild(backdrop);
    document.body.classList.add("overlay-open");
    stack.push({ backdrop: backdrop, frame: frame });
    closeBtn.focus();
    return false;
  }

  function closeOverlay() {
    var top = stack.pop();
    if (!top) return;
    top.backdrop.remove();
    if (!stack.length) document.body.classList.remove("overlay-open");
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && stack.length) closeOverlay();
  });

  // Links marked data-overlay open in place instead of navigating.
  document.addEventListener("click", function (e) {
    var link = e.target.closest ? e.target.closest("a[data-overlay]") : null;
    if (!link || !link.href) return;
    e.preventDefault();
    openOverlay(link.href);
  });

  window.AppOverlay = { open: openOverlay, close: closeOverlay };
})();
