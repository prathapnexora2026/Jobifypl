/* ============================================================================
   JobifyPL whole-app auto-translate.

   Goal: the ENTIRE app appears in the user's chosen language — every screen,
   label, button and every piece of user-written content — not just a few spots.

   How it works:
     • Walks the visible screen's text nodes, translates them into the current
       language in ONE batched request per 50 strings (server-cached), and swaps
       the text in. Originals are kept per-node so toggleTr() flips the page and
       a language switch re-translates cleanly.
     • A device cache (localStorage) means repeated UI strings translate instantly
       with no network call after the first time → fast + quota-safe.
     • A MutationObserver re-translates any screen the app re-renders, so new
       content is covered automatically without touching every render function.

   Skips: numbers/emails/URLs/phones/codes, <script>/<style>/<textarea>/<code>,
   contentEditable, and anything under [data-notr] (e.g. your own chat messages).

   English readers: the whole-page pass is skipped (the app is authored in
   English); only explicitly-requested spots (autoTr(el) on foreign content such
   as a job description or chat message) are translated INTO English.
   Requires a global api().
   ========================================================================== */
(function () {
  if (window.autoTrReady) return;
  window.autoTrReady = true;
  window._trShowOriginal = false;                 // false = show translations
  var SUPPORTED = { en: 1, pl: 1, uk: 1 };

  function lang() {
    return (localStorage.getItem("rec_lang") || localStorage.getItem("lang") || "en").toLowerCase().slice(0, 2);
  }

  /* ---------- device cache (localStorage, per language, real translations only) ---------- */
  var CC = {};
  function cc(l) {
    if (CC[l]) return CC[l];
    try { CC[l] = JSON.parse(localStorage.getItem("_trc_" + l) || "{}"); } catch (e) { CC[l] = {}; }
    return CC[l];
  }
  var _dirty = {};
  function ccPut(l, k, v) { cc(l)[k] = v; _dirty[l] = 1; }
  function ccFlush() {
    for (var l in _dirty) {
      try {
        var c = cc(l), keys = Object.keys(c);
        if (keys.length > 5000) keys.slice(0, keys.length - 5000).forEach(function (k) { delete c[k]; });
        localStorage.setItem("_trc_" + l, JSON.stringify(c));
      } catch (e) { /* quota/full — ignore */ }
    }
    _dirty = {};
  }

  /* ---------- what to skip ---------- */
  function skipParent(node) {
    var p = node.parentNode;
    if (!p || p.nodeType !== 1) return true;
    var tag = p.tagName;
    if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT" || tag === "TEXTAREA" ||
        tag === "CODE" || tag === "PRE" || tag === "OPTION" && false) return true;
    if (p.isContentEditable) return true;
    if (p.closest && p.closest("[data-notr]")) return true;
    return false;
  }
  var LETTER = /\p{L}/u;                                        // any Unicode letter (Latin, Polish, Cyrillic…)
  function skipText(s) {
    s = s.trim();
    if (s.length < 2) return true;
    if (!LETTER.test(s)) return true;                          // numbers / punctuation / symbols only
    if (/^[\w.+-]+@[\w.-]+\.\w+$/.test(s)) return true;        // email
    if (/^(https?:\/\/|www\.)/i.test(s)) return true;          // url
    if (/^\+?\d[\d\s().-]{5,}$/.test(s)) return true;          // phone
    if (/^[A-Z]{2,5}\d{2,6}$/.test(s)) return true;            // code like JPL123
    return false;
  }

  function collect(root, l) {
    var out = [], w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null), n;
    while ((n = w.nextNode())) {
      var v = n.nodeValue;
      if (!v || !v.trim()) continue;
      if (n.__trLang === l) continue;              // already translated for this language
      if (skipParent(n)) continue;
      if (skipText(v)) continue;
      out.push(n);
    }
    return out;
  }

  function put(node, l) {
    var orig = node.__trOrig, tr = node.__trText;
    node.__trLang = l;
    if (tr != null && !window._trShowOriginal && tr !== orig.trim()) {
      var m = orig.match(/^(\s*)([\s\S]*?)(\s*)$/);
      node.nodeValue = (m ? m[1] : "") + tr + (m ? m[3] : "");   // keep original whitespace
    }
  }

  /* ---------- translate every eligible text node under `root` into the current language ---------- */
  window.autoTr = async function (root) {
    root = root || document.querySelector(".screen.active") || document.body;
    var l = lang();
    if (!SUPPORTED[l] || typeof api !== "function") return;
    var nodes = collect(root, l);
    if (!nodes.length) return;
    var c = cc(l), need = [], texts = [], seen = {};
    nodes.forEach(function (n) {
      if (n.__trOrig == null) n.__trOrig = n.nodeValue;      // capture the original once
      var key = n.__trOrig.trim();
      if (c[key] != null) { n.__trText = c[key]; put(n, l); return; }   // device-cache hit
      need.push(n);
      if (!seen[key]) { seen[key] = 1; texts.push(key); }
    });
    for (var i = 0; i < texts.length; i += 50) {
      var chunk = texts.slice(i, i + 50);
      try {
        var r = await api("/translate/batch", { method: "POST", body: { texts: chunk, target: l } });
        var res = (r && r.results) || [];
        chunk.forEach(function (txt, j) {
          var t = res[j];
          if (t && t.translated && t.text) { c[txt] = t.text; ccPut(l, txt, t.text); }   // cache real translations only
        });
      } catch (e) { /* leave originals on failure */ }
    }
    need.forEach(function (n) { var k = n.__trOrig.trim(); if (c[k] != null) { n.__trText = c[k]; } put(n, l); });
    ccFlush();
    document.dispatchEvent(new CustomEvent("autotr:done"));
  };

  /* ---------- whole-page pass (skipped for English — app is authored in English) ----------
     Scoped to the whole body so popups/modals/other screens are covered too; the
     per-node "already translated" skip keeps repeat passes cheap. */
  window.autoTrPage = function () {
    if (lang() === "en") return;
    return window.autoTr(document.body);
  };

  /* Put every translated node back to its original text (used when switching to English). */
  function restore(root) {
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null), n;
    while ((n = w.nextNode())) { if (n.__trText != null && n.__trOrig != null) { n.nodeValue = n.__trOrig; n.__trLang = null; } }
  }

  /* ---------- the user changed language: re-translate (or restore for English) ---------- */
  window.autoTrRelang = function () {
    if (lang() === "en") { restore(document.body); return; }      // revert my translations everywhere
    var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null), n;
    while ((n = w.nextNode())) { if (n.__trLang) n.__trLang = null; }   // force re-translate; source stays __trOrig
    window.autoTr(document.body);
  };

  /* ---------- flip the visible screen between translation and original ---------- */
  window.toggleTr = function () {
    window._trShowOriginal = !window._trShowOriginal;
    var root = document.querySelector(".screen.active") || document.body;
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null), n;
    while ((n = w.nextNode())) {
      if (n.__trText != null && n.__trOrig != null) {
        var m = n.__trOrig.match(/^(\s*)([\s\S]*?)(\s*)$/), lead = m ? m[1] : "", trail = m ? m[3] : "";
        n.nodeValue = window._trShowOriginal ? n.__trOrig : (lead + n.__trText + trail);
      }
    }
    return window._trShowOriginal;   // true = now showing originals
  };

  /* ---------- auto-cover re-renders (debounced), + first pass on boot ---------- */
  var pending = null;
  function schedule() {
    if (pending || lang() === "en") return;
    pending = setTimeout(function () { pending = null; window.autoTrPage(); }, 250);
  }
  function init() {
    try {
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          if (muts[i].type === "childList" && muts[i].addedNodes.length) { schedule(); return; }
        }
      }).observe(document.body, { childList: true, subtree: true });
    } catch (e) { }
    window.autoTrPage();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
