/* Traducción en el navegador: usa el catálogo de /jsi18n/ si está cargado. */
function _t(s) { return window.gettext ? window.gettext(s) : s; }
function _tf(s, a) { var r = _t(s); for (var i = 0; i < a.length; i++) { r = r.replace("%s", a[i]); } return r; }
(function () {
  var raiz = document.getElementById("bienvenida");
  if (!raiz) return;
  var ahora = new Date();
  var hora = ahora.getHours();
  document.getElementById("bv-saludo").textContent =
    hora < 12 ? _t("Buenos días") : hora < 19 ? _t("Buenas tardes") : _t("Buenas noches");
  document.getElementById("bv-fecha").textContent =
    ahora.toLocaleDateString(document.documentElement.lang || "es-CO", { weekday: "long", day: "numeric", month: "long" });

  // Letra por letra con textContent: el nombre nunca se interpreta como HTML
  var caja = document.getElementById("bv-nombre");
  var nombre = raiz.dataset.nombre || "";
  caja.textContent = "";
  caja.setAttribute("aria-label", nombre);
  Array.from(nombre).forEach(function (c, i) {
    var s = document.createElement("span");
    s.className = "bv-letra";
    s.setAttribute("aria-hidden", "true");
    s.style.setProperty("--i", i);
    s.textContent = c === " " ? " " : c;
    caja.appendChild(s);
  });

  for (var k = 0; k < 26; k++) {
    var p = document.createElement("span");
    p.className = "bv-chispa";
    p.setAttribute("aria-hidden", "true");
    p.style.left = (8 + Math.random() * 84) + "%";
    p.style.top = (35 + Math.random() * 55) + "%";
    p.style.setProperty("--x", (Math.random() * 80 - 40) + "px");
    p.style.setProperty("--d", (3 + Math.random() * 3).toFixed(2) + "s");
    p.style.setProperty("--r", (Math.random() * 2.5).toFixed(2) + "s");
    raiz.appendChild(p);
  }

  var cerrado = false;
  function cerrar() {
    if (cerrado) return;
    cerrado = true;
    raiz.classList.add("bv-sale");
    document.removeEventListener("keydown", tecla);
    setTimeout(function () { raiz.remove(); }, 950);
  }
  function tecla(e) {
    if (e.key === "Escape" || e.key === "Enter" || e.key === " ") cerrar();
  }
  raiz.addEventListener("click", cerrar);
  document.addEventListener("keydown", tecla);
  setTimeout(cerrar, 4200);
})();
