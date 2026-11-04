/* Annual Inventory log page: entry form, number-only quantity, suggestions, row menu (details / edit / delete),
   inline edit, search, sorting. No inline scripts (CSP script-src 'self'). */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // ---------------------------------------------------------------- quantity: numbers only
  // Accepts 12, 12.5, .5 and 1,250.5 (thousands commas). Same rule as the server.
  var QTY = /^(\d+(\.\d+)?|\.\d+)$/;
  function qtyOk(v) { return QTY.test(v.trim().replace(/,/g, "")); }
  function qtyPartial(v) { return /^\d[\d,]*\.$/.test(v.trim()); }  // "12." while still typing
  function markQty(i) {
    var v = i.value.trim();
    i.classList.toggle("is-invalid", v !== "" && !qtyOk(v) && !qtyPartial(v));
  }
  $$("[data-qty]").forEach(function (i) {
    i.addEventListener("beforeinput", function (e) {
      // block letters and symbols as they are typed or pasted, and flash the hint
      if (e.data && /[^0-9.,]/.test(e.data)) {
        e.preventDefault();
        i.classList.add("is-invalid");
        clearTimeout(i._t);
        i._t = setTimeout(function () { markQty(i); }, 1200);
      }
    });
    i.addEventListener("input", function () { markQty(i); });
    i.addEventListener("blur", function () { var v = i.value.trim(); i.classList.toggle("is-invalid", v !== "" && !qtyOk(v)); });
  });

  // ---------------------------------------------------------------- entry no.: whole numbers only
  var NOPAT = /^[1-9]\d{0,8}$|^0*[1-9]\d{0,8}$/;  // 1..999999999 (leading zeros tolerated, 0 is not a number)
  function noOk(v) { return NOPAT.test(v.trim()); }
  $$("[data-int]").forEach(function (i) {
    i.addEventListener("beforeinput", function (e) {
      if (e.data && /\D/.test(e.data)) {
        e.preventDefault();
        i.classList.add("is-invalid");
        clearTimeout(i._t);
        i._t = setTimeout(function () { var v = i.value.trim(); i.classList.toggle("is-invalid", v !== "" && !noOk(v)); }, 1200);
      }
    });
    i.addEventListener("input", function () { var v = i.value.trim(); i.classList.toggle("is-invalid", v !== "" && !noOk(v)); });
  });
  // a field is fine when it is filled in and, if numeric, a valid number
  function fieldOk(i) {
    var v = i.value.trim();
    if (v === "") return false;
    if (i.hasAttribute("data-qty")) return qtyOk(v);
    if (i.hasAttribute("data-int")) return noOk(v);
    return true;
  }

  // ---------------------------------------------------------------- entry form
  var form = $("#annual-form"), enter = $("#annual-enter");
  if (form && enter) {
    var req = $$("[data-required]", form);
    var refresh = function () { enter.disabled = !req.every(fieldOk); };
    form.addEventListener("input", refresh);
    // Enter in any field submits (when the button is enabled); otherwise it moves to the first field to fix.
    form.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || e.target.tagName === "BUTTON") return;
      if (e.defaultPrevented) return;  // a suggestion was just chosen
      e.preventDefault();
      if (!enter.disabled) { form.requestSubmit ? form.requestSubmit(enter) : enter.click(); return; }
      var next = req.filter(function (i) { return !fieldOk(i); })[0];
      if (next) {
        next.focus();
        if ((next.hasAttribute("data-qty") || next.hasAttribute("data-int")) && next.value.trim()) next.classList.add("is-invalid");
      }
    });
    refresh();
    form.addEventListener("submit", function (e) { if (enter.disabled) e.preventDefault(); });
  }

  // ---------------------------------------------------------------- suggestions
  // Location: values already in the log. Item code (data-fill-loc): Odoo items matching the text, one row per
  // stock location; clicking a row fills the code and its location. Anything typed by hand is kept as is.
  $$("[data-suggest]").forEach(function (input) {
    var field = input.getAttribute("data-suggest"), fillSel = input.getAttribute("data-fill-loc");
    var min = 0;  // suggestions show from the first character, and when the empty field is clicked
    var list = document.createElement("div");
    list.className = "typeahead-list d-none";
    input.parentNode.appendChild(list);
    var items = [], idx = -1, timer = null, seq = 0;

    function hide() { list.classList.add("d-none"); idx = -1; }
    function pick(r) {
      input.value = r.code; hide();
      var loc = fillSel && r.location ? $(fillSel) : null;
      if (loc) loc.value = r.location;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      if (loc) { loc.dispatchEvent(new Event("input", { bubbles: true })); var q = $("#f-qty"); if (q) q.focus(); }
    }
    function mark() {
      $$("button", list).forEach(function (b, i) { b.classList.toggle("active", i === idx); });
      var a = $$("button", list)[idx]; if (a) a.scrollIntoView({ block: "nearest" });
    }
    function hilite(parent, text, q) {
      var at = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
      if (at < 0) { parent.appendChild(document.createTextNode(text)); return; }
      parent.appendChild(document.createTextNode(text.slice(0, at)));
      var m = document.createElement("b"); m.textContent = text.slice(at, at + q.length); parent.appendChild(m);
      parent.appendChild(document.createTextNode(text.slice(at + q.length)));
    }
    function show(rows) {
      items = rows; idx = -1; list.innerHTML = "";
      var q = input.value.trim();
      // nothing to suggest when the only match is exactly what is typed
      if (!rows.length || (rows.length === 1 && !rows[0].location && rows[0].code.toLowerCase() === q.toLowerCase())) { hide(); return; }
      rows.forEach(function (r) {
        var b = document.createElement("button");
        b.type = "button";
        hilite(b, r.code, q);
        if (r.description) { var d = document.createElement("span"); d.className = "ta-desc"; d.textContent = " " + r.description; b.appendChild(d); }
        if (r.location) {
          var l = document.createElement("span"); l.className = "ta-loc";
          l.textContent = "📍 " + r.location + (r.qty ? " · " + r.qty.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "");
          b.appendChild(l);
        }
        b.addEventListener("mousedown", function (e) { e.preventDefault(); pick(r); });
        list.appendChild(b);
      });
      list.classList.remove("d-none");
    }
    function fetchNow() {
      var q = input.value.trim();
      if (q.length < min) { hide(); return; }
      var mine = ++seq;
      var url = fillSel ? "/api/annual-inventory/lookup?q=" + encodeURIComponent(q)
                        : "/api/annual-inventory/suggest?field=" + field + "&q=" + encodeURIComponent(q);
      fetch(url, { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (rows) {
          if (mine !== seq || document.activeElement !== input) return;
          show(fillSel ? rows : rows.map(function (v) { return { code: v, description: "", location: "", qty: 0 }; }));
        })
        .catch(hide);
    }
    input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(fetchNow, 80); });
    input.addEventListener("focus", fetchNow);
    input.addEventListener("click", function () { if (list.classList.contains("d-none")) fetchNow(); });
    input.addEventListener("blur", function () { setTimeout(hide, 120); });
    input.addEventListener("keydown", function (e) {
      var open = !list.classList.contains("d-none");
      if (e.key === "ArrowDown" && open) { e.preventDefault(); idx = (idx + 1) % items.length; mark(); }
      else if (e.key === "ArrowUp" && open) { e.preventDefault(); idx = (idx - 1 + items.length) % items.length; mark(); }
      else if (e.key === "Escape" && open) { e.preventDefault(); hide(); }
      else if (e.key === "Enter" && open && idx >= 0) { e.preventDefault(); pick(items[idx]); }  // choose, don't submit
    });
  });

  var table = $("#annual-table");
  if (!table) return;
  var body = table.tBodies[0];
  var rows = $$("tr[data-id]", body);

  // ---------------------------------------------------------------- details mini modal
  var modal = $("#detail-modal"), modalFrom = null;
  function openDetails(tr, from) {
    var set = function (id, v) { $("#" + id).textContent = v; };
    set("dm-sub", tr.getAttribute("data-entry"));
    set("dm-code", tr.getAttribute("data-code"));
    set("dm-qty", tr.getAttribute("data-qtyfmt"));
    set("dm-loc", tr.getAttribute("data-loc"));
    set("dm-who", tr.getAttribute("data-who"));
    set("dm-at", tr.getAttribute("data-at"));
    set("dm-edited", tr.getAttribute("data-edited") || "Never");
    modalFrom = from || null;
    modal.hidden = false;
    document.body.classList.add("modal-open-oi");
    $(".oi-modal-box", modal).focus();
  }
  function closeDetails() {
    if (modal.hidden) return;
    modal.hidden = true;
    document.body.classList.remove("modal-open-oi");
    if (modalFrom) { try { modalFrom.focus(); } catch (e) {} }
  }
  modal.addEventListener("click", function (e) { if (e.target.closest("[data-modal-close]")) closeDetails(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDetails(); });

  // ---------------------------------------------------------------- row menu (three dots)
  function closeMenus(except) {
    $$(".kebab.open", body).forEach(function (k) {
      if (k !== except) { k.classList.remove("open"); $("[data-kebab]", k).setAttribute("aria-expanded", "false"); }
    });
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-kebab]");
    var k = btn ? btn.parentNode : null;
    closeMenus(k);
    if (k) {
      var open = k.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenus(null); });

  // ---------------------------------------------------------------- details / edit / cancel
  function refreshSave(tr) {
    var ok = $$("input.edit[data-required]", tr).every(fieldOk);
    var save = $("[data-save]", tr);
    if (save) save.disabled = !ok;
  }
  function setEditing(tr, on) {
    if (on) {
      rows.forEach(function (r) { if (r !== tr && r.classList.contains("editing")) setEditing(r, false); });
      tr.classList.add("editing");
      var f = $("input.edit[name=item_code]", tr); if (f) { f.focus(); f.select(); }
    } else {
      tr.classList.remove("editing");
      $$("input.edit", tr).forEach(function (i) { i.value = i.defaultValue; i.classList.remove("is-invalid"); });
    }
    refreshSave(tr);
  }
  // Cancel an edit; if anything was typed, offer Undo in a toast that brings the typed values back.
  function cancelEdit(tr) {
    var inputs = $$("input.edit", tr);
    var typed = inputs.map(function (i) { return i.value; });
    var changed = inputs.some(function (i) { return i.value !== i.defaultValue; });
    setEditing(tr, false);
    if (!changed || !window.oicasToast) return;
    window.oicasToast("Edit cancelled for " + tr.getAttribute("data-code") + ".", "warning", { action: { label: "Undo", run: function () {
      setEditing(tr, true);
      inputs.forEach(function (i, n) { i.value = typed[n]; markQty(i); });
      refreshSave(tr);
    } } });
  }
  table.addEventListener("click", function (e) {
    var det = e.target.closest("[data-details]"), ed = e.target.closest("[data-edit]"), ca = e.target.closest("[data-cancel]");
    if (det) {
      var menuBtn = $("[data-kebab]", det.closest(".kebab"));
      closeMenus(null);
      openDetails(det.closest("tr"), menuBtn);
    } else if (ed) {
      closeMenus(null);
      setEditing(ed.closest("tr"), true);
    } else if (ca) {
      cancelEdit(ca.closest("tr"));
    }
  });
  body.addEventListener("input", function (e) { var tr = e.target.closest("tr.editing"); if (tr) refreshSave(tr); });
  body.addEventListener("keydown", function (e) {
    var tr = e.target.closest("tr.editing");
    if (!tr) return;
    if (e.key === "Escape") cancelEdit(tr);
    else if (e.key === "Enter" && e.target.tagName === "INPUT") {
      e.preventDefault();
      var save = $("[data-save]", tr), f = document.getElementById("edit-" + tr.getAttribute("data-id"));
      if (f && save && !save.disabled) f.requestSubmit(save);
    }
  });
  $$("form.edit-actions", body).forEach(function (f) {
    f.addEventListener("submit", function (e) { var s = $("[data-save]", f); if (s && s.disabled) e.preventDefault(); });
  });

  // ---------------------------------------------------------------- search + reconciliation filter
  // Clicking a reconciliation badge shows only that item code; clicking it again, the Reconciliation
  // heading or the chip's x shows everything again. The search box works on top of it.
  var search = $("#annual-search"), reconCode = "";
  function setRecon(code) {
    reconCode = (code || "").toLowerCase();
    var on = reconCode !== "";
    $$("[data-recon]", body).forEach(function (b) {
      b.classList.toggle("recon-active", on && b.getAttribute("data-recon").toLowerCase() === reconCode);
    });
    $("#recon-chip").classList.toggle("d-none", !on);
    $("#recon-chip-code").textContent = on ? code : "";
    $("#recon-th").classList.toggle("recon-th-on", on);
    $(".recon-th-ic", $("#recon-th")).classList.toggle("d-none", !on);
    apply();
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-recon]"), clr = e.target.closest("[data-recon-clear]");
    if (b) setRecon(reconCode === b.getAttribute("data-recon").toLowerCase() ? "" : b.getAttribute("data-recon"));
    else if (clr && reconCode) setRecon("");
  });
  function apply() {
    var q = search.value.trim().toLowerCase(), shown = 0;
    rows.forEach(function (tr) {
      var ok = (!q || (tr.getAttribute("data-search") || "").toLowerCase().indexOf(q) >= 0) &&
               (!reconCode || (tr.getAttribute("data-code") || "").toLowerCase() === reconCode);
      tr.classList.toggle("d-none", !ok);
      if (ok) shown++;
    });
    var none = shown === 0;
    $("#annual-empty").classList.toggle("d-none", !none);
    $("#annual-nomatch").classList.toggle("d-none", !(none && rows.length));
    $("#annual-none").classList.toggle("d-none", !(none && !rows.length));
    $("#annual-count").textContent = "(" + (shown === rows.length ? rows.length : shown + " of " + rows.length) + ")";
    var foot = $("#annual-foot");
    if (foot && rows.length) foot.textContent = "Showing " + shown + " of " + rows.length + " entries";
  }
  search.addEventListener("input", apply);

  // ---------------------------------------------------------------- sorting (click a header)
  $$("thead th[data-sort]", table).forEach(function (th) {
    var col = th.cellIndex;  // the column's real position (not every column is sortable)
    th.addEventListener("click", function () {
      var dir = th.classList.contains("sort-asc") ? -1 : 1, num = th.getAttribute("data-sort") === "num";
      $$("thead th[data-sort]", table).forEach(function (h) { h.classList.remove("sort-asc", "sort-desc"); });
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      rows.sort(function (a, b) {
        var x = a.cells[col].getAttribute("data-v") || "", y = b.cells[col].getAttribute("data-v") || "";
        var r = num ? (parseFloat(x) - parseFloat(y)) : x.localeCompare(y, undefined, { numeric: true, sensitivity: "base" });
        return r * dir;
      });
      var anchor = $("#annual-empty");
      rows.forEach(function (tr) { body.insertBefore(tr, anchor); });
    });
  });
  apply();
})();
