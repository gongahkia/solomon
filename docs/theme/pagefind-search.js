(function () {
  const mount = document.getElementById("pagefind-search");
  if (!mount) return;

  const root = typeof path_to_root === "string" ? path_to_root : "";
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = root + "pagefind/pagefind-ui.css";
  document.head.appendChild(css);

  const script = document.createElement("script");
  script.src = root + "pagefind/pagefind-ui.js";
  script.onload = function () {
    new window.PagefindUI({
      element: "#pagefind-search",
      showSubResults: true,
      excerptLength: 24
    });
  };
  script.onerror = function () {
    mount.textContent = "Search index unavailable.";
  };
  document.body.appendChild(script);
})();
