(function () {
  var form = document.getElementById("pedidos-filtros-form");
  if (!form) return;
  form.querySelectorAll("select[data-auto-enviar]").forEach(function (select) {
    select.addEventListener("change", function () {
      form.submit();
    });
  });
})();
