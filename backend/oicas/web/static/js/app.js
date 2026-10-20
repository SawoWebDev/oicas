/* OICAS front-end behaviour. No inline scripts (CSP script-src 'self'). */
(function () {
  "use strict";

  // Sidebar toggle (mobile)
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-toggle-sidebar]");
    if (t) document.body.classList.toggle("sidebar-open");
    var c = e.target.closest("[data-confirm]");
    if (c && !window.confirm(c.getAttribute("data-confirm"))) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  // Auto-submit filter selects
  document.querySelectorAll("form[data-autosubmit] select").forEach(function (s) {
    s.addEventListener("change", function () { s.form.submit(); });
  });

  // Select-all checkbox
  document.querySelectorAll("[data-check-all]").forEach(function (box) {
    box.addEventListener("change", function () {
      document.querySelectorAll(box.getAttribute("data-check-all")).forEach(function (c) { c.checked = box.checked; });
    });
  });

  // Prevent double submission of forms (server is idempotent too)
  document.querySelectorAll("form[method=post]").forEach(function (f) {
    f.addEventListener("submit", function () {
      setTimeout(function () { f.querySelectorAll("button[type=submit], button:not([type])").forEach(function (b) { b.disabled = true; }); }, 0);
    });
  });

  // Item typeahead for count entry
  document.querySelectorAll("[data-typeahead]").forEach(function (input) {
    var list = document.createElement("div");
    list.className = "typeahead-list d-none";
    input.parentNode.appendChild(list);
    var timer = null;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 2) { list.classList.add("d-none"); return; }
      timer = setTimeout(function () {
        fetch("/api/items/search?q=" + encodeURIComponent(q), { credentials: "same-origin" })
          .then(function (r) { return r.ok ? r.json() : []; })
          .then(function (rows) {
            list.innerHTML = "";
            rows.forEach(function (row) {
              var b = document.createElement("button");
              b.type = "button";
              b.textContent = row.code + " — " + (row.description || "") + (row.uom ? " (" + row.uom + ")" : "");
              b.addEventListener("click", function () { input.value = row.code; list.classList.add("d-none"); });
              list.appendChild(b);
            });
            list.classList.toggle("d-none", rows.length === 0);
          });
      }, 200);
    });
    document.addEventListener("click", function (e) { if (!list.contains(e.target) && e.target !== input) list.classList.add("d-none"); });
  });

  // ---------------------------------------------------------------- Help (F1 / ? button)
  var helpPanel = document.getElementById("help-panel");
  var helpBody = document.getElementById("help-body");
  function openHelp(topic) {
    if (!helpPanel || !window.bootstrap) return;
    topic = topic || document.body.getAttribute("data-help") || "overview";
    helpBody.innerHTML = '<div class="muted small">Loading…</div>';
    fetch("/help/topic/" + encodeURIComponent(topic), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : fetch("/help/topic/login").then(function (x) { return x.text(); }); })
      .then(function (html) {
        helpBody.innerHTML = html;
        helpBody.scrollTop = 0;
        var center = document.getElementById("help-open-center");
        if (center) center.setAttribute("href", "/help#help-" + topic);
      })
      .catch(function () { helpBody.innerHTML = '<div class="text-danger small">Help could not be loaded.</div>'; });
    bootstrap.Offcanvas.getOrCreateInstance(helpPanel).show();
  }
  var fab = document.getElementById("help-fab");
  if (fab) fab.addEventListener("click", function () { openHelp(); });
  if (helpBody) helpBody.addEventListener("click", function (e) {
    var a = e.target.closest("[data-help-topic]");
    if (a) { e.preventDefault(); openHelp(a.getAttribute("data-help-topic")); }
  });
  var typing = function (el) { return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)); };
  document.addEventListener("keydown", function (e) {
    if (e.key === "F1") { e.preventDefault(); openHelp(); return; }
    if (e.key === "?" && !typing(document.activeElement) && !e.ctrlKey && !e.metaKey) { e.preventDefault(); openHelp(); }
  });
  window.addEventListener("help", function (e) { e.preventDefault && e.preventDefault(); openHelp(); });  // legacy IE/Edge F1
  var jump = document.getElementById("help-jump");
  if (jump) jump.addEventListener("change", function () { location.hash = jump.value; });
  // Help Center page: highlight anchor
  if (location.pathname === "/help" && location.hash) {
    var t = document.querySelector(location.hash);
    if (t) t.scrollIntoView();
  }

  // Charts: <canvas data-chart="kind" data-source="json-script-id" data-key="...">
  if (window.Chart) {
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = "#6b7280";
    var BRAND = "#d7191f", GREEN = "#1f9d55", BLUE = "#2563eb", ORANGE = "#e8710a", GRAY = "#9ca3af", PURPLE = "#8b3fd9", YELLOW = "#a16207";
    var pct = function (v) { return v == null ? "–" : (v * 100).toFixed(2) + "%"; };
    var data = function (el) {
      var src = document.getElementById(el.getAttribute("data-source"));
      return src ? JSON.parse(src.textContent) : {};
    };
    document.querySelectorAll("canvas[data-chart]").forEach(function (el) {
      var d = data(el), kind = el.getAttribute("data-chart"), cfg = null;
      if (kind === "classes" && d.classes) {
        var c = d.classes;
        cfg = { type: "bar", data: { labels: c.labels, datasets: [
          { label: "Count completion", data: c.completion, backgroundColor: BLUE, borderRadius: 4 },
          { label: "Inventory accuracy (count based)", data: c.accuracy, backgroundColor: PURPLE, borderRadius: 4 },
          { type: "line", label: "Overall accuracy", data: c.overall_accuracy, borderColor: GREEN, backgroundColor: GREEN },
          { type: "line", label: "Discrepancy rate", data: c.discrepancy_rate, borderColor: "#1d2330", backgroundColor: "#1d2330" }
        ] }, options: { maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { callback: pct } } },
          plugins: { tooltip: { callbacks: { label: function (x) { return x.dataset.label + ": " + pct(x.raw); } } } } } };
      } else if (kind === "weekly" && d.weekly) {
        var w = d.weekly;
        cfg = { type: "bar", data: { labels: w.labels, datasets: [
          { label: "Counted", data: w.counted, backgroundColor: "#1f4e79", borderRadius: 4, yAxisID: "y" },
          { label: "Discrepancy", data: w.discrepancy, backgroundColor: ORANGE, borderRadius: 4, yAxisID: "y" },
          { type: "line", label: "Accuracy %", data: w.accuracy, borderColor: BRAND, backgroundColor: BRAND, yAxisID: "y1", spanGaps: true }
        ] }, options: { maintainAspectRatio: false, scales: { y: { beginAtZero: true }, y1: { position: "right", beginAtZero: true, max: 1,
          grid: { drawOnChartArea: false }, ticks: { callback: pct } } } } };
      } else if (kind === "doughnut") {
        var key = el.getAttribute("data-key"), s = key ? d[key] : d;
        if (s && s.labels && s.labels.length) {
          cfg = { type: "doughnut", data: { labels: s.labels, datasets: [{ data: s.values,
            backgroundColor: [GREEN, "#34c77b", "#86efac", BLUE, "#60a5fa", YELLOW, ORANGE, BRAND, GRAY] }] },
            options: { maintainAspectRatio: false, plugins: { legend: { position: "right" } } } };
        }
      }
      if (cfg) new Chart(el, cfg);
      else el.parentNode.innerHTML = '<div class="chart-empty">No data yet</div>';
    });
  }
})();
