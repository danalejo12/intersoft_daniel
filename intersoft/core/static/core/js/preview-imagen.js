(function () {
  document.querySelectorAll("[data-preview-imagen]").forEach(function (cfg) {
    var input = document.getElementById(cfg.dataset.previewInput || "");
    var preview = document.getElementById(cfg.dataset.previewTarget || "");
    var nombre = document.getElementById(cfg.dataset.previewNombre || "");
    var alt = cfg.dataset.previewAlt || "Vista previa";
    if (!input || !preview || !nombre) return;

    input.addEventListener("change", function () {
      var archivo = input.files && input.files[0];
      if (!archivo) return;
      nombre.textContent = archivo.name;
      var lector = new FileReader();
      lector.onload = function (ev) {
        preview.innerHTML = "";
        var img = document.createElement("img");
        img.src = ev.target.result;
        img.alt = alt;
        preview.appendChild(img);
      };
      lector.readAsDataURL(archivo);
    });
  });
})();
