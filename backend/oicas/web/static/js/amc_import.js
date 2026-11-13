/* AMC Import: large modal viewer for an uploaded workbook (sheet tabs, search, paging) and upload feedback. */
(function () {
  "use strict";
  var modal = document.getElementById("amc-modal");
  if (!modal) return;
  var box = document.getElementById("amc-modal-box");
  var loadingHtml = '<div class="amc-loading"><span class="spinner-border spinner-border-sm"></span> Loading…</div>';
  var state = { iid: null, sheet: 0, page: 1, q: "", hidden: 0, from: null, req: 0 };
  var searchTimer = null;

  function get(url) {
    return fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } }).then(function (r) {
      if (r.redirected && /\/login/.test(r.url)) { window.location = "/login?next=" + encodeURIComponent(location.pathname); throw new Error("login"); }
      return r.text().then(function (t) { return { ok: r.ok, html: t }; });
    });
  }

  function loadSheet() {
    var grid = document.getElementById("amc-grid");
    if (!grid) return;
    var my = ++state.req;
    grid.classList.add("is-loading");
    var url = "/amc-import/" + state.iid + "/sheets/" + state.sheet + "?page=" + state.page + "&q=" + encodeURIComponent(state.q) + "&hidden=" + state.hidden;
    get(url).then(function (res) {
      if (my !== state.req) return; // a newer request replaced this one
      grid.innerHTML = res.html;
      grid.classList.remove("is-loading");
      var sc = grid.querySelector(".amc-scroll");
      if (sc) sc.scrollTop = 0;
    }).catch(function (e) {
      if (my !== state.req || e.message === "login") return;
      grid.classList.remove("is-loading");
      grid.innerHTML = '<div class="amc-error">Could not load the sheet. Check the connection and try again.</div>';
    });
  }

  function open(iid, from) {
    state = { iid: iid, sheet: 0, page: 1, q: "", hidden: 0, from: from || null, req: state.req };
    box.innerHTML = loadingHtml;
    modal.hidden = false;
    document.body.classList.add("modal-open-oi");
    box.focus();
    get("/amc-import/" + iid + "/view").then(function (res) {
      box.innerHTML = res.html;
      if (!res.ok) return;
      // start on the sheet Excel opens on (the workbook's active tab), like opening the file
      var grid = document.getElementById("amc-grid");
      state.sheet = (grid && grid.getAttribute("data-sheet")) || 0;
      revealTab(box.querySelector(".amc-tab.active"));
      var zs = document.getElementById("amc-zoom");
      if (zs) zs.value = savedZoom();
      applyZoom(savedZoom());
      loadSheet();
    }).catch(function (e) {
      if (e.message !== "login") box.innerHTML = '<div class="amc-error">Could not open this session.</div>';
    });
  }

  // ---- sheet bar (tabs, arrows, all-sheets list)
  function revealTab(tab) {
    var bar = document.getElementById("amc-tabs");
    if (!tab || !bar) return;
    var l = tab.offsetLeft - bar.offsetLeft, r = l + tab.offsetWidth;
    if (l < bar.scrollLeft) bar.scrollLeft = l - 8;
    else if (r > bar.scrollLeft + bar.clientWidth) bar.scrollLeft = r - bar.clientWidth + 8;
  }

  function selectSheet(pos) {
    pos = String(pos);
    var name = "";
    box.querySelectorAll(".amc-tab, .amc-sheetmenu-item").forEach(function (b) {
      var on = b.getAttribute("data-amc-sheet") === pos;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
      if (on && b.classList.contains("amc-tab")) { name = b.textContent.trim(); revealTab(b); }
    });
    var nm = document.getElementById("amc-sheet-name");
    if (nm && name) nm.textContent = name;
    state.sheet = pos;
    state.page = 1;
    state.hidden = 0;
    loadSheet();
  }

  // zoom: 100% shows the sheet at Excel's own size (the page itself is scaled by --ui-zoom, this cancels it)
  var zoomKey = "amc_zoom";
  function applyZoom(v) {
    var g = document.getElementById("amc-grid");
    if (g) g.style.setProperty("--amc-z", (parseInt(v, 10) || 100) / 100);
  }
  function savedZoom() { try { return localStorage.getItem(zoomKey) || "100"; } catch (e) { return "100"; } }

  function menuOpen() { var m = document.getElementById("amc-sheetmenu"); return m && !m.hidden; }

  function toggleMenu(show) {
    var m = document.getElementById("amc-sheetmenu"), b = document.getElementById("amc-menu-btn");
    if (!m) return;
    m.hidden = !show;
    if (b) b.setAttribute("aria-expanded", show ? "true" : "false");
    if (show) {
      var f = document.getElementById("amc-sheet-filter");
      if (f) { f.value = ""; filterMenu(""); f.focus(); }
      var a = m.querySelector(".amc-sheetmenu-item.active");
      if (a) a.scrollIntoView({ block: "nearest" });
    }
  }

  function filterMenu(text) {
    var m = document.getElementById("amc-sheetmenu");
    if (!m) return;
    var t = text.trim().toLowerCase(), shown = 0;
    m.querySelectorAll(".amc-sheetmenu-item").forEach(function (b) {
      var ok = !t || b.getAttribute("data-name").indexOf(t) !== -1;
      b.hidden = !ok;
      shown += ok ? 1 : 0;
    });
    var none = m.querySelector(".amc-sheetmenu-none");
    if (none) none.hidden = shown > 0;
  }

  function close() {
    if (modal.hidden) return;
    modal.hidden = true;
    state.req++;
    box.innerHTML = loadingHtml;
    document.body.classList.remove("modal-open-oi");
    if (state.from) { try { state.from.focus(); } catch (e) { /* element gone */ } }
  }

  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-amc-open]");
    if (t) { open(t.getAttribute("data-amc-open"), t); return; }
    if (modal.hidden) return;
    if (e.target.closest("[data-amc-close]")) { close(); return; }
    if (e.target.closest("[data-amc-menu]")) { toggleMenu(!menuOpen()); return; }
    if (menuOpen() && !e.target.closest(".amc-sheetmenu")) toggleMenu(false);
    var sc = e.target.closest("[data-amc-tabscroll]");
    if (sc) {
      var bar = document.getElementById("amc-tabs");
      if (bar) bar.scrollBy({ left: parseInt(sc.getAttribute("data-amc-tabscroll"), 10) * bar.clientWidth * 0.6, behavior: "smooth" });
      return;
    }
    var tab = e.target.closest("[data-amc-sheet]");
    if (tab) {
      toggleMenu(false);
      selectSheet(tab.getAttribute("data-amc-sheet"));
      return;
    }
    var hd = e.target.closest("[data-amc-hidden]");
    if (hd) { state.hidden = parseInt(hd.getAttribute("data-amc-hidden"), 10) || 0; state.page = 1; loadSheet(); return; }
    var pg = e.target.closest("[data-amc-page]");
    if (pg && !pg.closest(".disabled")) { state.page = parseInt(pg.getAttribute("data-amc-page"), 10) || 1; loadSheet(); }
  });

  document.addEventListener("change", function (e) {
    if (e.target.id !== "amc-zoom") return;
    applyZoom(e.target.value);
    try { localStorage.setItem(zoomKey, e.target.value); } catch (err) { /* private mode */ }
  });

  document.addEventListener("input", function (e) {
    if (e.target.id === "amc-sheet-filter") { filterMenu(e.target.value); return; }
    if (e.target.id !== "amc-q") return;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { state.q = e.target.value.trim(); state.page = 1; loadSheet(); }, 300);
  });

  document.addEventListener("keydown", function (e) {
    if (modal.hidden) return;
    if (e.key === "Escape") {
      e.preventDefault();
      if (menuOpen()) { toggleMenu(false); var b = document.getElementById("amc-menu-btn"); if (b) b.focus(); }
      else close();
      return;
    }
    // Enter in the sheet list's search opens the first matching sheet
    if (e.key === "Enter" && e.target.id === "amc-sheet-filter") {
      e.preventDefault();
      var first = document.querySelector(".amc-sheetmenu-item:not([hidden])");
      if (first) { toggleMenu(false); selectSheet(first.getAttribute("data-amc-sheet")); }
    }
  });

  // after an upload the page comes back with ?open=<id>: show the new session straight away
  var params = new URLSearchParams(location.search);
  if (params.get("open")) {
    var iid = params.get("open");
    params.delete("open");
    history.replaceState(null, "", location.pathname + (params.toString() ? "?" + params : ""));
    if (/^\d+$/.test(iid)) open(iid, document.querySelector('[data-amc-open="' + iid + '"]'));
  }

  // upload: a big workbook takes a few seconds to read; show it and prevent a double submit
  var form = document.getElementById("amc-upload-form");
  if (form) form.addEventListener("submit", function () {
    var b = document.getElementById("amc-upload-btn");
    if (b) { b.disabled = true; b.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Reading workbook…'; }
  });
})();
