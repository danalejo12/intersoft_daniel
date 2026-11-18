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
      var etiqueta = boton.querySelector("span") || boton;
      var textoOriginal = etiqueta.textContent;
      boton.disabled = true;
      etiqueta.textContent = "Añadiendo…";

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
        etiqueta.textContent = datos.ok ? "¡Añadido!" : textoOriginal;
        window.setTimeout(function () {
          etiqueta.textContent = textoOriginal;
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

  // ---------- Modo día / noche ----------
  // El tema inicial lo pone un script en <head> (sin parpadeo); aquí solo se cambia y se recuerda.
  function iniciarTema() {
    var raiz = document.documentElement;
    var boton = document.querySelector("[data-tema-boton]");
    if (!boton) {
      return;
    }
    function pintar() {
      var oscuro = raiz.getAttribute("data-tema") === "oscuro";
      boton.setAttribute("aria-checked", oscuro ? "true" : "false");
      boton.title = oscuro ? "Cambiar a modo día" : "Cambiar a modo noche";
    }
    boton.addEventListener("click", function () {
      var nuevo = raiz.getAttribute("data-tema") === "oscuro" ? "claro" : "oscuro";
      if (!sinMovimiento) {
        raiz.classList.add("cambiando-tema");
        window.setTimeout(function () { raiz.classList.remove("cambiando-tema"); }, 500);
      }
      raiz.setAttribute("data-tema", nuevo);
      try { localStorage.setItem("intersoft-tema", nuevo); } catch (e) { /* modo privado: solo dura la visita */ }
      pintar();
    });
    pintar();
  }

  // ---------- Menús desplegables (<details>): se cierran al hacer clic fuera o con Esc ----------
  function iniciarDesplegables() {
    var menus = document.querySelectorAll("[data-desplegable]");
    document.addEventListener("click", function (evento) {
      menus.forEach(function (menu) {
        if (menu.open && !menu.contains(evento.target)) {
          menu.open = false;
        }
      });
    });
    document.addEventListener("keydown", function (evento) {
      if (evento.key !== "Escape") {
        return;
      }
      menus.forEach(function (menu) {
        if (menu.open) {
          menu.open = false;
          menu.querySelector("summary").focus();
        }
      });
    });
  }

  // ---------- "Ordenar por" se aplica al elegir, sin botón ----------
  function iniciarAutoenvio() {
    document.querySelectorAll("[data-autoenvio] select").forEach(function (selector) {
      selector.addEventListener("change", function () { selector.form.submit(); });
    });
  }

  // ---------- Galería: la miniatura elegida pasa a la foto grande ----------
  function iniciarGaleria() {
    var principal = document.querySelector("[data-galeria-principal]");
    if (!principal) {
      return;
    }
    var miniaturas = document.querySelectorAll("[data-galeria-foto]");
    miniaturas.forEach(function (mini) {
      mini.addEventListener("click", function (evento) {
        evento.preventDefault();
        miniaturas.forEach(function (m) { m.removeAttribute("aria-current"); });
        mini.setAttribute("aria-current", "true");
        principal.classList.add("cambiando");
        window.setTimeout(function () {
          principal.src = mini.getAttribute("href");
          principal.classList.remove("cambiando");
        }, sinMovimiento ? 0 : 150);
      });
    });
  }

  // ---------- Sugerencias del buscador (autocompletar accesible) ----------
  function iniciarSugerencias() {
    var formulario = document.querySelector("[data-sugerencias]");
    if (!formulario || !window.fetch) {
      return;
    }
    var campo = formulario.querySelector('input[name="q"]');
    var lista = document.getElementById("sugerencias");
    var url = formulario.getAttribute("data-sugerencias");
    var ESPERA_MS = 180;
    var temporizador = null;
    var pedido = 0;
    var activa = -1;

    function opciones() { return lista.querySelectorAll('[role="option"]'); }
    function cerrar() {
      lista.hidden = true;
      campo.setAttribute("aria-expanded", "false");
      campo.removeAttribute("aria-activedescendant");
      activa = -1;
    }
    function marcar(indice) {
      var todas = opciones();
      if (!todas.length) { return; }
      activa = (indice + todas.length) % todas.length;
      todas.forEach(function (o, i) { o.setAttribute("aria-selected", i === activa ? "true" : "false"); });
      campo.setAttribute("aria-activedescendant", todas[activa].id);
      todas[activa].scrollIntoView({ block: "nearest" });
    }
    function opcion(id, enlace, contenido) {
      var a = document.createElement("a");
      a.id = id;
      a.href = enlace;
      a.className = "sugerencia";
      a.setAttribute("role", "option");
      a.setAttribute("aria-selected", "false");
      contenido(a);
      return a;
    }
    function titulo(texto) {
      var t = document.createElement("p");
      t.className = "sugerencias-titulo";
      t.textContent = texto;
      return t;
    }
    // Todo se arma con textContent: los nombres nunca se interpretan como HTML
    function pintar(datos) {
      lista.textContent = "";
      if (datos.productos.length) {
        lista.appendChild(titulo("Productos"));
        datos.productos.forEach(function (p, i) {
          lista.appendChild(opcion("sug-p-" + i, p.url, function (a) {
            var foto = document.createElement(p.imagen ? "img" : "span");
            foto.className = "sugerencia-foto";
            if (p.imagen) { foto.src = p.imagen; foto.alt = ""; foto.loading = "lazy"; }
            var texto = document.createElement("span");
            texto.className = "sugerencia-texto";
            var nombre = document.createElement("strong");
            nombre.textContent = p.nombre;
            var negocio = document.createElement("small");
            negocio.textContent = p.negocio;
            texto.appendChild(nombre);
            texto.appendChild(negocio);
            var precio = document.createElement("span");
            precio.className = "sugerencia-precio";
            precio.textContent = p.precio;
            a.appendChild(foto);
            a.appendChild(texto);
            a.appendChild(precio);
          }));
        });
      }
      if (datos.negocios.length) {
        lista.appendChild(titulo("Tiendas"));
        datos.negocios.forEach(function (n, i) {
          lista.appendChild(opcion("sug-n-" + i, n.url, function (a) {
            var texto = document.createElement("span");
            texto.className = "sugerencia-texto";
            var nombre = document.createElement("strong");
            nombre.textContent = n.nombre;
            texto.appendChild(nombre);
            a.appendChild(texto);
          }));
        });
      }
      lista.appendChild(opcion("sug-todo", formulario.action + "?q=" + encodeURIComponent(campo.value.trim()), function (a) {
        a.classList.add("sugerencia-todo");
        a.textContent = "Ver todos los resultados para «" + campo.value.trim() + "»";
      }));
      lista.hidden = false;
      campo.setAttribute("aria-expanded", "true");
      activa = -1;
    }
    function buscar() {
      var q = campo.value.trim();
      if (q.length < 2) { cerrar(); return; }
      var numero = ++pedido;
      fetch(url + "?q=" + encodeURIComponent(q), { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) { return r.json(); })
        .then(function (datos) { if (numero === pedido) { pintar(datos); } })
        .catch(cerrar);
    }
    campo.addEventListener("input", function () {
      window.clearTimeout(temporizador);
      temporizador = window.setTimeout(buscar, ESPERA_MS);
    });
    campo.addEventListener("keydown", function (e) {
      if (lista.hidden) { return; }
      if (e.key === "ArrowDown") { e.preventDefault(); marcar(activa + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); marcar(activa - 1); }
      else if (e.key === "Escape") { cerrar(); }
      else if (e.key === "Enter" && activa >= 0) { e.preventDefault(); window.location.href = opciones()[activa].href; }
    });
    document.addEventListener("click", function (e) { if (!formulario.contains(e.target)) { cerrar(); } });
  }

  iniciarTema();
  iniciarDesplegables();
  iniciarAutoenvio();
  iniciarSugerencias();
  iniciarGaleria();
  iniciarBarra();
  iniciarTarjetas();
  iniciarAgregar();
  iniciarCantidades();
  iniciarEnvioUnico();
  iniciarEsperaPago();
})();


/* Selector moderno de categorías en el buscador */
(function () {
  var hidden = document.getElementById("buscador-categoria");
  var menu = document.querySelector(".buscador-filtro-menu");
  if (!hidden || !menu) return;
  var texto = menu.querySelector("[data-filtro-texto]");
  var form = menu.closest("form");
  menu.addEventListener("click", function (ev) {
    var boton = ev.target.closest("[data-filtro-valor]");
    if (!boton) return;
    var valor = boton.getAttribute("data-filtro-valor") || "";
    hidden.value = valor;
    if (texto) texto.textContent = valor || "Todas";
    menu.querySelectorAll(".buscador-filtro-opcion").forEach(function (b) {
      b.classList.toggle("activa", b === boton);
    });
    menu.removeAttribute("open");
    if (form) form.submit();
  });
})();

/* Confirmación declarativa en formularios de la tienda */
(function () {
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!(form instanceof HTMLFormElement)) return;
    var msg = form.getAttribute("data-confirmar");
    if (msg && !window.confirm(msg)) {
      ev.preventDefault();
    }
  });
})();
