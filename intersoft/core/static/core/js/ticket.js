(function () {
  var btnCerrar = document.getElementById("ticket-cerrar");
  var btnImprimir = document.getElementById("ticket-imprimir");
  if (btnCerrar) btnCerrar.addEventListener("click", function () { window.close(); });
  if (btnImprimir) btnImprimir.addEventListener("click", function () { window.print(); });
  if (document.body.dataset.autoImprimir === "1") {
    window.addEventListener("load", function () { window.print(); });
  }
  var formCorreo = document.querySelector(".form-correo");
  if (formCorreo) {
    formCorreo.addEventListener("submit", function () {
      var btn = formCorreo.querySelector('button[type="submit"]');
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Enviando…";
      }
    });
  }
})();
