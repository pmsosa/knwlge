// Applies the saved theme before the page draws (no flash). "system" follows the device's light/dark setting.
(function () {
  var pick = null;
  try { pick = localStorage.getItem("knwlge-theme"); } catch (e) { /* private mode */ }
  if (pick === "light" || pick === "dark") document.documentElement.dataset.theme = pick;
  var dark = pick === "dark" || (pick !== "light" && window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", dark ? "#161615" : "#efefe4");
})();
