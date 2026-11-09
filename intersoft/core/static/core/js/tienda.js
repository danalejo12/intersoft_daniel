/* Solo mejora la experiencia: sin este archivo todos los formularios siguen funcionando. */
(function () {
  "use strict";

  var sinMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- Sombra de la barra y aparición de tarjetas ----------
  function iniciarBarra() {
    var barra = document.querySelector(".barra");
    var centinela = document.getElementById("centinela-barra");
    if (!barra || !centinela || !("IntersectionObserver" in window)) {
      return;
    }
    new IntersectionObserver(function (entradas) {
      barra.classList.toggle("con-sombra", !entradas[0].isIntersecting);
    }).observe(centinela);
  }

  function iniciarTarjetas() {
    if (sinMovimiento || !("IntersectionObserver" in window)) {
      return;
    }
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
  }

  // ---------- Avisos flotantes ----------
  function avisar(mensaje, correcto) {
    var contenedor = document.getElementById("avisos");
    if (!contenedor) {
      return;
    }
    var aviso = document.createElement("div");
    aviso.className = "aviso" + (correcto ? " aviso-ok" : " aviso-alerta");
    var texto = document.createElement("span");
    texto.textContent = mensaje;  // textContent: el nombre del producto nunca se interpreta como HTML
    aviso.appendChild(texto);
    if (correcto) {
      var enlace = document.createElement("a");
      enlace.href = document.querySelector("[data-carrito]").getAttribute("href");
      enlace.textContent = "Ver carrito";
      aviso.appendChild(enlace);
    }
    contenedor.appendChild(aviso);
    window.setTimeout(function () { aviso.remove(); }, 4500);
  }

  function pintarCarrito(cantidad) {
    var contador = document.querySelector("[data-carrito-cantidad]");
    if (!contador) {
      return;
    }
    contador.textContent = cantidad;
    contador.hidden = !cantidad;
    contador.classList.remove("rebote");
    void contador.offsetWidth;  // reinicia la animación aunque ya se haya usado
    contador.classList.add("rebote");
  }

  // ---------- Añadir al carrito sin salir de la página ----------
  function iniciarAgregar() {
    document.addEventListener("submit", function (evento) {
      var formulario = evento.target;
      if (!formulario.matches("[data-agregar]")) {
        return;
      }
      if (evento.submitter && evento.submitter.name === "comprar_ahora") {
        return;
      }
      evento.preventDefault();
      var boton = evento.submitter || formulario.querySelector("button[type=submit]");
      var textoOriginal = boton.textContent;
      boton.disabled = true;
      boton.textContent = "Añadiendo…";

      fetch(formulario.action, {
        method: "POST",
        body: new FormData(formulario),
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      }).then(function (respuesta) {
        return respuesta.json();
      }).then(function (datos) {
        avisar(datos.mensaje, datos.ok);
        pintarCarrito(datos.cantidad_total);
        boton.textContent = datos.ok ? "¡Añadido!" : textoOriginal;
        window.setTimeout(function () {
          boton.textContent = textoOriginal;
          boton.disabled = false;
        }, 1200);
      }).catch(function () {
        formulario.submit();  // si falla la red o el JSON, se envía de la forma normal
      });
    });
  }

  // ---------- Botones + y − ----------
  function iniciarCantidades() {
    document.querySelectorAll("[data-cantidad]").forEach(function (selector) {
      var campo = selector.querySelector("input");
      var formulario = selector.closest("form");
      function cambiar(diferencia) {
        var valor = Math.min(Math.max((parseInt(campo.value, 10) || 1) + diferencia, 0), 99);
        // Solo en el carrito se puede llegar a 0, que significa quitar el producto
        if (valor === 0 && !formulario.matches("[data-auto-enviar]")) {
          return;
        }
        campo.value = valor;
        campo.dispatchEvent(new Event("change", { bubbles: true }));
      }
      selector.querySelector("[data-menos]").addEventListener("click", function () { cambiar(-1); });
      selector.querySelector("[data-mas]").addEventListener("click", function () { cambiar(1); });
      if (formulario.matches("[data-auto-enviar]")) {
        campo.addEventListener("change", function () { formulario.submit(); });
      }
    });
  }

  // ---------- Evita crear dos pedidos con un doble clic ----------
  function iniciarEnvioUnico() {
    document.querySelectorAll("[data-un-envio]").forEach(function (formulario) {
      formulario.addEventListener("submit", function () {
        var boton = formulario.querySelector("button[type=submit]");
        window.setTimeout(function () {
          boton.disabled = true;
          boton.textContent = "Guardando tu pedido…";
        }, 0);
      });
    });
  }

  // ---------- Espera el resultado del pago mientras se paga en la pestaña de Wompi ----------
  function iniciarEsperaPago() {
    var zona = document.querySelector("[data-esperar-pago]");
    if (!zona) {
      return;
    }
    var INTERVALO_MS = 5000;
    var MAXIMO_MS = 15 * 60 * 1000;
    var estadoInicial = zona.dataset.estado;
    var temporizador = null;
    var inicio = 0;
    var consultando = false;

    function consultar() {
      if (consultando) {
        return;
      }
      consultando = true;
      fetch(zona.dataset.url, { credentials: "same-origin" })
        .then(function (respuesta) { return respuesta.json(); })
        .then(function (datos) {
          if (datos.estado !== estadoInicial) {
            window.location.reload();
          }
        })
        .catch(function () { /* se reintenta en la siguiente vuelta */ })
        .finally(function () { consultando = false; });
    }

    function vigilar() {
      if (temporizador) {
        return;
      }
      inicio = Date.now();
      temporizador = window.setInterval(function () {
        if (Date.now() - inicio > MAXIMO_MS) {
          window.clearInterval(temporizador);
          temporizador = null;
          return;
        }
        consultar();
      }, INTERVALO_MS);
    }

    var formulario = document.querySelector("[data-pagar]");
    if (formulario) {
      formulario.addEventListener("submit", function () {
        var texto = document.querySelector("[data-espera-texto]");
        if (texto) {
          texto.hidden = false;
        }
        vigilar();
      });
    }
    // Al volver de la pestaña de Wompi se revisa de inmediato, sin esperar la siguiente vuelta
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && temporizador) {
        consultar();
      }
    });
    if (zona.hasAttribute("data-activo")) {
      vigilar();
    }
  }

  iniciarBarra();
  iniciarTarjetas();
  iniciarAgregar();
  iniciarCantidades();
  iniciarEnvioUnico();
  iniciarEsperaPago();
})();
