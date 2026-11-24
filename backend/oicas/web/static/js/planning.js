/* Cycle Count Planning: entry form helper. No inline scripts (CSP script-src 'self'). */
(function () {
  "use strict";
  var form = document.getElementById("cp-entry");
  if (!form) return;
  var code = document.getElementById("cp-code"), desc = document.getElementById("cp-desc"),
      cls = document.getElementById("cp-class"), plant = document.getElementById("cp-plant"),
      date = document.getElementById("cp-date"), msg = document.getElementById("cp-msg");
  var looked = "", seq = 0;

  function fill(d) {
    desc.value = d ? d.description : ""; cls.value = d ? d.classification : ""; plant.value = d ? d.plant_location : "";
  }
  function lookup() {
    var v = code.value.trim();
    if (v === looked) return Promise.resolve();
    looked = v; var my = ++seq;
    if (!v) { fill(null); msg.textContent = ""; return Promise.resolve(); }
    return fetch("/planning/lookup?month=" + encodeURIComponent(form.elements.month.value) + "&code=" + encodeURIComponent(v), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (my !== seq) return;
        if (d.found) {
          code.value = d.code; fill(d); code.setCustomValidity("");
          date.value = d.adjusted_date || d.original_date;
          msg.textContent = "Original date: " + d.original_date;
        } else {
          fill(null); date.value = "";
          code.setCustomValidity("This code is not in this month's list");
          msg.textContent = "Not in this month's list. Import the Inventory Masterlist first.";
        }
      })
      .catch(function () { msg.textContent = "Lookup failed."; });
  }
  code.addEventListener("input", function () { code.setCustomValidity(""); });
  code.addEventListener("keydown", function (e) {
    if (e.key === "Tab" && !e.shiftKey) {  // Tab runs the lookup first, then lands on Description
      e.preventDefault(); lookup().then(function () { desc.focus(); });
    } else if (e.key === "Enter") { e.preventDefault(); lookup().then(function () { date.focus(); }); }
  });
  code.addEventListener("change", lookup);
  form.addEventListener("submit", function (e) {
    if (code.value.trim() !== looked) {  // submitted before the lookup finished
      e.preventDefault(); lookup().then(function () { if (form.reportValidity()) form.submit(); });
    }
  });
})();

/* Editable list: rows turn "changed" when a value differs from what was loaded; the Save bar appears below. */
(function () {
  "use strict";
  var form = document.getElementById("cp-save-form"), bar = document.getElementById("cp-savebar");
  if (!form || !bar) return;
  var rows = Array.prototype.slice.call(form.querySelectorAll("tr[data-row]"));
  var count = document.getElementById("cp-dirty-count");
  // inputs start disabled (so they are not sent); enable the editable ones for display
  function inputs(r) { return Array.prototype.slice.call(r.querySelectorAll("input[data-orig]")); }
  function dirty(r) { return inputs(r).some(function (i) { return i.value !== i.getAttribute("data-orig"); }); }
  rows.forEach(function (r) { inputs(r).forEach(function (i) { i.disabled = false; }); });
  function refresh() {
    var n = 0;
    rows.forEach(function (r) { var d = dirty(r); r.classList.toggle("cp-dirty", d); if (d) n++; });
    count.textContent = n + (n === 1 ? " row changed" : " rows changed");
    bar.hidden = n === 0;
  }
  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  document.getElementById("cp-discard").addEventListener("click", function () {
    rows.forEach(function (r) { inputs(r).forEach(function (i) { i.value = i.getAttribute("data-orig"); }); });
    refresh();
  });
  form.addEventListener("submit", function () {
    rows.forEach(function (r) {
      var d = dirty(r), hid = r.querySelector("input[name=code]");
      if (hid) hid.disabled = !d;
      inputs(r).forEach(function (i) { i.disabled = !d; });
    });
  });
  window.addEventListener("beforeunload", function (e) {
    if (!bar.hidden && !form.dataset.sent) { e.preventDefault(); e.returnValue = ""; }
  });
  form.addEventListener("submit", function () { form.dataset.sent = "1"; });
})();

/* Import schedule: the button opens the file picker (the confirm, if any, is data-confirm in app.js); choosing a file sends it. */
(function () {
  "use strict";
  var btn = document.getElementById("cp-sched-btn"), file = document.getElementById("cp-sched-file"),
      form = document.getElementById("cp-sched-form");
  if (!btn || !file || !form) return;
  btn.addEventListener("click", function () { file.click(); });
  file.addEventListener("change", function () { if (file.files.length) { btn.disabled = true; form.submit(); } });
})();
