(function () {
  var btnAbrir = document.getElementById("pos-escanear-camara");
  var dialogo = document.getElementById("pos-camara-dialogo");
  var video = document.getElementById("pos-camara-video");
  var estado = document.getElementById("pos-camara-estado");
  var btnCerrar = document.getElementById("pos-camara-cerrar");
  var inputBuscar = document.getElementById("pos-buscar");

  if (!btnAbrir || !dialogo || !video || !inputBuscar) return;

  var streamActivo = null;
  var escaneando = false;
  var ultimoTick = 0;

  function detenerCamara() {
    escaneando = false;
    if (streamActivo) {
      streamActivo.getTracks().forEach(function (t) { t.stop(); });
      streamActivo = null;
    }
    video.srcObject = null;
  }

  function cerrar() {
    detenerCamara();
    if (dialogo.open) dialogo.close();
  }

  async function iniciarEscaneo() {
    if (!dialogo.open) dialogo.showModal();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (estado) estado.textContent = "Este navegador o conexión no permite usar la cámara (requiere HTTPS).";
      return;
    }

    if (estado) estado.textContent = "Abriendo cámara…";
    try {
      streamActivo = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false
      });
      video.srcObject = streamActivo;
      await video.play();
    } catch (err) {
      if (estado) estado.textContent = "No se pudo acceder a la cámara. Revisa los permisos del navegador.";
      return;
    }

    if (!("BarcodeDetector" in window)) {
      if (estado) estado.textContent = "Cámara activa, pero este navegador no soporta detección automática de códigos (usa Chrome/Edge en Android).";
      return;
    }

    var detector = new window.BarcodeDetector({
      formats: ["ean_13", "ean_8", "code_128", "code_39", "upc_a", "upc_e", "qr_code"]
    });
    escaneando = true;
    if (estado) estado.textContent = "Apunta el código de barras dentro del recuadro…";

    async function ciclo(ahora) {
      if (!escaneando) return;
      if (ahora - ultimoTick >= 180 && video.readyState >= 2) {
        ultimoTick = ahora;
        try {
          var codigos = await detector.detect(video);
          if (codigos && codigos.length > 0 && codigos[0].rawValue) {
            var valor = codigos[0].rawValue.trim();
            cerrar();
            inputBuscar.value = valor;
            inputBuscar.focus();
            inputBuscar.dispatchEvent(new Event("input", { bubbles: true }));
            inputBuscar.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
            return;
          }
        } catch (e) {}
      }
      window.requestAnimationFrame(ciclo);
    }
    window.requestAnimationFrame(ciclo);
  }

  btnAbrir.addEventListener("click", iniciarEscaneo);
  if (btnCerrar) btnCerrar.addEventListener("click", cerrar);
  dialogo.addEventListener("close", detenerCamara);
})();
