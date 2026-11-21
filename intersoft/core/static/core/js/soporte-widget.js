/* Traducción en el navegador: usa el catálogo de /jsi18n/ si está cargado. */
function _t(s) { return window.gettext ? window.gettext(s) : s; }
function _tf(s, a) { var r = _t(s); for (var i = 0; i < a.length; i++) { r = r.replace("%s", a[i]); } return r; }
(function () {
  var form = document.getElementById("nps-form");
  if (!form) return;

  var estado = document.getElementById("nps-estado");
  var comentario = document.getElementById("nps-comentario");
  var radios = form.querySelectorAll('input[name="puntaje"]');

  var mensajes = {
    detractor: _t("Gracias por tu sinceridad. ¿Qué deberíamos mejorar?"),
    pasivo: _t("¡Gracias! ¿Qué nos falta para llegar al 10?"),
    promotor: _t("¡Qué alegría! ¿Qué es lo que más valoras de InterSoft?")
  };

  radios.forEach(function (radio) {
    radio.addEventListener("change", function () {
      var val = parseInt(radio.value, 10);
      var grupo = val <= 6 ? "detractor" : val <= 8 ? "pasivo" : "promotor";
      if (estado) {
        estado.textContent = _tf("Puntaje elegido: %s/10 · %s", [val, mensajes[grupo]]);
      }
      if (comentario) {
        comentario.placeholder = mensajes[grupo] + " (opcional)";
      }
    });
  });
})();
