(function () {
  var btnCopiar = document.getElementById("btn-copiar-webhook");
  var urlEl = document.getElementById("webhook-url-texto");
  if (btnCopiar && urlEl) {
    btnCopiar.addEventListener("click", function () {
      var texto = (urlEl.textContent || "").trim();
      if (!texto) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texto).then(function () {
          btnCopiar.textContent = "¡Copiada!";
          setTimeout(function () { btnCopiar.textContent = "Copiar URL"; }, 2200);
        });
      }
    });
  }

  var formBorrar = document.getElementById("form-borrar-pagos");
  if (formBorrar) {
    formBorrar.addEventListener("submit", function (ev) {
      var msg = formBorrar.dataset.confirmar || "¿Borrar tus llaves de Wompi?";
      if (!window.confirm(msg)) {
        ev.preventDefault();
      }
    });
  }
})();
