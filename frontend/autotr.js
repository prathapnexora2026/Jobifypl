/* ============================================================================
   JobifyPL auto-translate — makes user-written content (job descriptions, chat,
   CV free-text) appear in the reader's chosen language automatically.

   Usage:
     1) Mark any dynamic-text element with the `data-tr` attribute.
     2) After rendering, call  autoTr(containerEl)  (or autoTr() for the document).
   It batch-translates all not-yet-done [data-tr] elements in ONE request (cached
   server-side), then swaps the text in. Originals are kept, so toggleTr() flips
   the whole page between translated and original. Requires a global api().
   ========================================================================== */
(function () {
  if (window.autoTr) return;
  window._trShowOriginal = false;   // false = show translations (default)

  function lang() { return (localStorage.getItem("lang") || "en").toLowerCase().slice(0, 2); }

  window.autoTr = async function (root) {
    root = root || document;
    var els = Array.prototype.slice.call(root.querySelectorAll("[data-tr]:not([data-tr-done])"));
    if (!els.length || typeof api !== "function") return;
    els.forEach(function (e) {
      e.setAttribute("data-tr-done", "1");
      e.setAttribute("data-tr-orig", e.textContent);
    });
    var texts = els.map(function (e) { return e.textContent; });
    try {
      var r = await api("/translate/batch", { method: "POST", body: { texts: texts, target: lang() } });
      var res = (r && r.results) || [];
      els.forEach(function (e, i) {
        var t = res[i];
        if (t && t.translated && t.text && t.text !== e.getAttribute("data-tr-orig")) {
          e.setAttribute("data-tr-trans", t.text);
          if (!window._trShowOriginal) e.textContent = t.text;
          // let the page reveal a "translated" hint if it wants
          e.setAttribute("data-tr-has", "1");
        }
      });
      document.dispatchEvent(new CustomEvent("autotr:done"));
    } catch (e) { /* leave originals on failure */ }
  };

  // Flip the whole page between translated text and the original.
  window.toggleTr = function () {
    window._trShowOriginal = !window._trShowOriginal;
    Array.prototype.slice.call(document.querySelectorAll("[data-tr-trans]")).forEach(function (e) {
      e.textContent = window._trShowOriginal ? e.getAttribute("data-tr-orig") : e.getAttribute("data-tr-trans");
    });
    return window._trShowOriginal;   // true = now showing originals
  };
})();
