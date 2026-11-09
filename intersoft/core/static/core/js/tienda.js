/* Solo mejora la presentación: si este archivo no carga, todo el contenido sigue visible. */
(function () {
  "use strict";

  if (!("IntersectionObserver" in window)) {
    return;
  }

  // Sombra de la barra: aparece cuando el marcador del inicio de la página sale de la pantalla
  var barra = document.querySelector(".barra");
  var centinela = document.getElementById("centinela-barra");
  if (barra && centinela) {
    new IntersectionObserver(function (entradas) {
      barra.classList.toggle("con-sombra", !entradas[0].isIntersecting);
    }).observe(centinela);
  }

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  // Las tarjetas aparecen escalonadas la primera vez que entran en pantalla
  var RETRASO_MS = 60;
  var MAXIMO_ESCALONES = 7;

  var observador = new IntersectionObserver(function (entradas, observer) {
    var orden = 0;
    entradas.forEach(function (entrada) {
      if (!entrada.isIntersecting) {
        return;
      }
      entrada.target.style.setProperty("--retraso", Math.min(orden, MAXIMO_ESCALONES) * RETRASO_MS + "ms");
      entrada.target.classList.remove("oculta");
      entrada.target.classList.add("visible");
      observer.unobserve(entrada.target);
      orden += 1;
    });
  });

  document.querySelectorAll(".tarjeta").forEach(function (tarjeta) {
    tarjeta.classList.add("oculta");
    observador.observe(tarjeta);
  });
})();
