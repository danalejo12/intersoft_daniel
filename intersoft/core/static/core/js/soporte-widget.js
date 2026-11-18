(function () {
  var form = document.getElementById("nps-form");
  if (!form) return;

  var estado = document.getElementById("nps-estado");
  var comentario = document.getElementById("nps-comentario");
  var radios = form.querySelectorAll('input[name="puntaje"]');

  var mensajes = {
    detractor: "Gracias por tu sinceridad. ¿Qué deberíamos mejorar?",
    pasivo: "¡Gracias! ¿Qué nos falta para llegar al 10?",
    promotor: "¡Qué alegría! ¿Qué es lo que más valoras de InterSoft?"
  };

  radios.forEach(function (radio) {
    radio.addEventListener("change", function () {
      var val = parseInt(radio.value, 10);
      var grupo = val <= 6 ? "detractor" : val <= 8 ? "pasivo" : "promotor";
      if (estado) {
        estado.textContent = "Puntaje elegido: " + val + "/10 · " + mensajes[grupo];
      }
      if (comentario) {
        comentario.placeholder = mensajes[grupo] + " (opcional)";
      }
    });
  });
})();
