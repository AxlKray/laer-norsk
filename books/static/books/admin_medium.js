(function () {
  // Analog: physical fields (location, stock). Digital: PDF fields. Both: everything.
  var PHYSICAL = ["shelf_location", "branch", "location2", "quantity_in_stock", "loan_status"];
  var DIGITAL = ["pdf_file", "pdf_url"];
  function row(name) { return document.querySelector(".form-row.field-" + name); }
  function apply() {
    var a = document.querySelector("input[name=medium][value=analog]"), d = document.querySelector("input[name=medium][value=digital]");
    var v = (a && a.checked && d && d.checked) ? "both" : (d && d.checked ? "digital" : "analog");
    PHYSICAL.forEach(function (n) { var r = row(n); if (r) r.style.display = v === "digital" ? "none" : ""; });
    DIGITAL.forEach(function (n) { var r = row(n); if (r) r.style.display = v === "analog" ? "none" : ""; });
  }
  document.addEventListener("DOMContentLoaded", function () {
    var boxes = document.querySelectorAll("input[name=medium]");
    if (!boxes.length) return;
    boxes.forEach(function (b) { b.addEventListener("change", apply); });
    apply();
  });
})();
