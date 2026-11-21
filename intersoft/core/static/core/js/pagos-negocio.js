/* Traducción en el navegador: usa el catálogo de /jsi18n/ si está cargado. */
function _t(s) { return window.gettext ? window.gettext(s) : s; }
function _tf(s, a) { var r = _t(s); for (var i = 0; i < a.length; i++) { r = r.replace("%s", a[i]); } return r; }
(function () {
  var btnCopiar = document.getElementById("btn-copiar-webhook");
  var urlEl = document.getElementById("webhook-url-texto");
  if (btnCopiar && urlEl) {
    btnCopiar.addEventListener("click", function () {
      var texto = (urlEl.textContent || "").trim();
      if (!texto) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texto).then(function () {
          btnCopiar.textContent = _t("¡Copiada!");
          setTimeout(function () { btnCopiar.textContent = _t("Copiar URL"); }, 2200);
        });
      }
    });
  }

  var formBorrar = document.getElementById("form-borrar-pagos");
  if (formBorrar) {
    formBorrar.addEventListener("submit", function (ev) {
      var msg = formBorrar.dataset.confirmar || _t("¿Borrar tus llaves de Wompi?");
      if (!window.confirm(msg)) {
        ev.preventDefault();
      }
    });
  }
})();
