(function () {
  var root = document.documentElement;
  var storageKey = "intersoft-tema";

  // 1. Toggle Claro / Oscuro respetando prefers-color-scheme
  var mediaDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var btnTema = document.querySelector("[data-plat-tema]");

  function temaEfectivo() {
    var guardado = root.dataset.tema;
    if (guardado === "light" || guardado === "dark") return guardado;
    return mediaDark && mediaDark.matches ? "dark" : "light";
  }

  function actualizarBotonTema() {
    if (!btnTema) return;
    var esOscuro = temaEfectivo() === "dark";
    btnTema.setAttribute("aria-pressed", esOscuro ? "true" : "false");
    btnTema.setAttribute("aria-label", esOscuro ? "Cambiar a tema claro" : "Cambiar a tema oscuro");
    var lbl = btnTema.querySelector("[data-plat-tema-label]");
    if (lbl) lbl.textContent = esOscuro ? "Oscuro" : "Claro";
  }

  if (btnTema) {
    actualizarBotonTema();
    btnTema.addEventListener("click", function () {
      var siguiente = temaEfectivo() === "dark" ? "light" : "dark";
      root.dataset.tema = siguiente;
      try {
        localStorage.setItem(storageKey, siguiente === "dark" ? "oscuro" : "claro");
      } catch (e) {}
      actualizarBotonTema();
    });
  }

  if (mediaDark && typeof mediaDark.addEventListener === "function") {
    mediaDark.addEventListener("change", actualizarBotonTema);
  }

  // 2. Drawer lateral en pantallas pequeñas
  var sidebar = document.getElementById("plat-sidebar");
  var backdrop = document.querySelector("[data-plat-backdrop]");
  var btnAbrir = document.querySelector("[data-plat-menu]");
  var btnCerrar = document.querySelector("[data-plat-cerrar]");

  function setDrawer(abierto) {
    if (!sidebar) return;
    sidebar.classList.toggle("abierto", abierto);
    if (backdrop) backdrop.hidden = !abierto;
    if (btnAbrir) btnAbrir.setAttribute("aria-expanded", abierto ? "true" : "false");
    if (abierto && btnCerrar) {
      btnCerrar.focus();
    } else if (!abierto && btnAbrir && document.activeElement && sidebar.contains(document.activeElement)) {
      btnAbrir.focus();
    }
  }

  if (btnAbrir) {
    btnAbrir.addEventListener("click", function () {
      var abierto = sidebar && sidebar.classList.contains("abierto");
      setDrawer(!abierto);
    });
  }
  if (btnCerrar) {
    btnCerrar.addEventListener("click", function () { setDrawer(false); });
  }
  if (backdrop) {
    backdrop.addEventListener("click", function () { setDrawer(false); });
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && sidebar && sidebar.classList.contains("abierto")) {
      setDrawer(false);
    }
  });
})();
