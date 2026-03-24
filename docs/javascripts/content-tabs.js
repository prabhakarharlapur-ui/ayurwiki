/* Content tabs — switches between Article and Contributors panes */
function initTabs() {
  document.querySelectorAll(".aw-tab-bar").forEach(function (bar) {
    bar.addEventListener("click", function (e) {
      var btn = e.target.closest(".aw-tab");
      if (!btn || btn.classList.contains("active")) return;
      var tabs = bar.closest(".aw-tabs");
      bar.querySelectorAll(".aw-tab").forEach(function (b) { b.classList.remove("active"); });
      tabs.querySelectorAll(":scope > .aw-tab-pane").forEach(function (p) { p.classList.remove("active"); });
      btn.classList.add("active");
      var pane = tabs.querySelector(':scope > .aw-tab-pane[data-tab="' + btn.dataset.tab + '"]');
      if (pane) pane.classList.add("active");
    });
  });
}

/* Support MkDocs Material instant navigation */
if (typeof document$ !== "undefined") {
  document$.subscribe(initTabs);
} else {
  document.addEventListener("DOMContentLoaded", initTabs);
}
