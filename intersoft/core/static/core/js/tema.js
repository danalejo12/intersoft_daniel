/* Interruptor día / noche del panel y de la consola de plataforma.
   El tema inicial lo pone tema-init.js en <head> (sin parpadeo); aquí solo se cambia y se recuerda.
   Usa la misma preferencia ("intersoft-tema") que el marketplace. */
(function () {
  var raiz = document.documentElement;
  var sinMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  document.querySelectorAll("[data-tema-boton]").forEach(function (boton) {
    function pintar() {
      var oscuro = raiz.getAttribute("data-tema") === "oscuro";
      boton.setAttribute("aria-checked", oscuro ? "true" : "false");
      boton.title = oscuro ? "Cambiar a modo día" : "Cambiar a modo noche";
    }
    boton.addEventListener("click", function () {
      var nuevo = raiz.getAttribute("data-tema") === "oscuro" ? "claro" : "oscuro";
      if (!sinMovimiento) {
        raiz.classList.add("cambiando-tema");
        window.setTimeout(function () { raiz.classList.remove("cambiando-tema"); }, 500);
      }
      raiz.setAttribute("data-tema", nuevo);
      try { localStorage.setItem("intersoft-tema", nuevo); } catch (e) { /* modo privado: solo dura la visita */ }
      pintar();
    });
    pintar();
  });
})();
