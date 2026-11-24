/* Buscador global (paleta de comandos) del panel y de la consola de plataforma.
   Se abre con Ctrl+K / Cmd+K, con "/" o al tocar el buscador de la barra. Los comandos vienen del HTML
   (#paleta-comandos), ya filtrados por permisos en el servidor. Archivo externo: la CSP no permite scripts
   en línea. Sin JavaScript, el buscador de la barra sigue buscando productos como antes. */
(function () {
  var fuente = document.getElementById("paleta-comandos");
  if (!fuente) return;

  var CLAVE_RECIENTES = "intersoft-paleta-recientes";
  var MAX_RECIENTES = 5;
  var ORDEN_GRUPOS = ["Recientes", "Resultados", "Crear", "Ir a", "Buscar", "Preferencias"];

  function normalizar(texto) {
    return (texto || "").toString().normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  }

  var comandos = Array.prototype.map.call(fuente.querySelectorAll("li"), function (li, i) {
    var etiqueta = li.textContent.trim();
    return {
      id: i,
      etiqueta: etiqueta,
      grupo: li.dataset.grupo || "Ir a",
      url: li.dataset.url || "",
      buscar: li.dataset.buscar || "",
      accion: li.dataset.accion || "",
      indice: normalizar(etiqueta + " " + (li.dataset.claves || "")),
      etiquetaNorm: normalizar(etiqueta),
    };
  });

  // ---------- Estructura (se crea una vez) ----------
  var fondo = document.createElement("div");
  fondo.className = "paleta-fondo";
  fondo.hidden = true;
  fondo.innerHTML =
    '<div class="paleta" role="dialog" aria-modal="true" aria-label="Buscar o ir a">' +
    '  <div class="paleta-entrada">' +
    '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
    '    <input type="text" role="combobox" aria-expanded="true" aria-controls="paleta-lista" aria-autocomplete="list" autocomplete="off" spellcheck="false" placeholder="¿Qué quieres hacer? Busca una sección, una acción o un producto…">' +
    '    <kbd>Esc</kbd>' +
    '  </div>' +
    '  <ul class="paleta-lista" id="paleta-lista" role="listbox" aria-label="Resultados"></ul>' +
    '  <p class="paleta-pie"><kbd>↑</kbd><kbd>↓</kbd> moverte · <kbd>Enter</kbd> abrir · <kbd>Ctrl</kbd>+<kbd>K</kbd> en cualquier pantalla</p>' +
    "</div>";
  document.body.appendChild(fondo);

  var entrada = fondo.querySelector("input");
  var lista = fondo.querySelector(".paleta-lista");
  var resultados = [];
  var activo = 0;
  var focoAnterior = null;

  // ---------- Recientes ----------
  function leerRecientes() {
    try { return JSON.parse(localStorage.getItem(CLAVE_RECIENTES) || "[]"); } catch (e) { return []; }
  }
  function guardarReciente(cmd) {
    if (!cmd.url) return;
    try {
      var lista_ = leerRecientes().filter(function (r) { return r.url !== cmd.url; });
      lista_.unshift({ url: cmd.url, etiqueta: cmd.etiqueta });
      localStorage.setItem(CLAVE_RECIENTES, JSON.stringify(lista_.slice(0, MAX_RECIENTES)));
    } catch (e) { /* modo privado: no se recuerda */ }
  }

  // ---------- Búsqueda ----------
  function puntaje(cmd, palabras, consulta) {
    for (var i = 0; i < palabras.length; i++) {
      if (cmd.indice.indexOf(palabras[i]) === -1) return -1;   // todas las palabras deben aparecer
    }
    if (cmd.etiquetaNorm.indexOf(consulta) === 0) return 3;
    if (cmd.etiquetaNorm.indexOf(consulta) !== -1) return 2;
    return 1;
  }

  function calcular(texto) {
    var consulta = normalizar(texto);
    var navegables = comandos.filter(function (c) { return !c.buscar; });
    if (!consulta) {
      var vistos = {};
      var recientes = leerRecientes()
        .map(function (r) {
          var cmd = navegables.filter(function (c) { return c.url === r.url; })[0];
          return cmd ? { cmd: cmd, grupo: "Recientes" } : null;
        })
        .filter(function (r) { return r && !vistos[r.cmd.url] && (vistos[r.cmd.url] = true); });
      return recientes.concat(navegables.map(function (c) { return { cmd: c, grupo: c.grupo }; }));
    }
    var palabras = consulta.split(/\s+/);
    var encontrados = navegables
      .map(function (c) { return { cmd: c, grupo: "Resultados", p: puntaje(c, palabras, consulta) }; })
      .filter(function (r) { return r.p > 0; })
      .sort(function (a, b) { return b.p - a.p; });
    var busquedas = comandos
      .filter(function (c) { return c.buscar; })
      .map(function (c) {
        return {
          cmd: c, grupo: "Buscar",
          etiqueta: "Buscar «" + texto.trim() + "» en " + c.etiqueta,
          url: c.buscar + (c.buscar.indexOf("?") === -1 ? "?" : "&") + "q=" + encodeURIComponent(texto.trim()),
        };
      });
    return encontrados.concat(busquedas);
  }

  function pintar() {
    resultados = calcular(entrada.value);
    if (!entrada.value.trim()) {
      // Sin texto: por grupos (Recientes, Crear, Ir a…). Con texto ya viene ordenado por coincidencia.
      resultados.sort(function (a, b) {
        return ORDEN_GRUPOS.indexOf(a.grupo) - ORDEN_GRUPOS.indexOf(b.grupo);
      });
    }
    activo = 0;
    lista.innerHTML = "";
    var grupoActual = null;
    resultados.forEach(function (r, i) {
      if (r.grupo !== grupoActual) {
        grupoActual = r.grupo;
        var titulo = document.createElement("li");
        titulo.className = "paleta-grupo";
        titulo.setAttribute("role", "presentation");
        titulo.textContent = r.grupo;
        lista.appendChild(titulo);
      }
      var li = document.createElement("li");
      li.className = "paleta-item";
      li.id = "paleta-op-" + i;
      li.setAttribute("role", "option");
      li.dataset.indice = i;
      li.textContent = r.etiqueta || r.cmd.etiqueta;
      lista.appendChild(li);
    });
    if (!resultados.length) {
      var vacio = document.createElement("li");
      vacio.className = "paleta-vacio";
      vacio.textContent = "No encontramos nada con ese nombre.";
      lista.appendChild(vacio);
    }
    marcar();
  }

  function marcar() {
    lista.querySelectorAll(".paleta-item").forEach(function (li) {
      var sel = Number(li.dataset.indice) === activo;
      li.classList.toggle("activo", sel);
      li.setAttribute("aria-selected", sel ? "true" : "false");
      if (sel) {
        entrada.setAttribute("aria-activedescendant", li.id);
        li.scrollIntoView({ block: "nearest" });
      }
    });
  }

  function ejecutar(r) {
    if (!r) return;
    if (r.cmd.accion === "tema") {
      cerrar();
      var boton = document.querySelector("[data-tema-boton]");
      if (boton) boton.click();
      return;
    }
    var destino = r.url || r.cmd.url;
    if (!r.url) guardarReciente(r.cmd);
    window.location.href = destino;
  }

  // ---------- Abrir / cerrar ----------
  function abrir(textoInicial) {
    if (!fondo.hidden) return;
    focoAnterior = document.activeElement;
    fondo.hidden = false;
    document.documentElement.classList.add("paleta-abierta");
    entrada.value = textoInicial || "";
    pintar();
    entrada.focus();
  }
  function cerrar() {
    if (fondo.hidden) return;
    entrada.blur();                       // que el foco no se quede en un campo oculto
    fondo.hidden = true;
    document.documentElement.classList.remove("paleta-abierta");
    if (focoAnterior && focoAnterior.focus && !focoAnterior.hasAttribute("data-paleta-abrir")) focoAnterior.focus();
  }

  entrada.addEventListener("input", pintar);
  entrada.addEventListener("keydown", function (ev) {
    if (ev.key === "ArrowDown") { ev.preventDefault(); activo = Math.min(activo + 1, resultados.length - 1); marcar(); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); activo = Math.max(activo - 1, 0); marcar(); }
    else if (ev.key === "Enter") { ev.preventDefault(); ejecutar(resultados[activo]); }
    else if (ev.key === "Escape") { ev.preventDefault(); cerrar(); }
    else if (ev.key === "Tab") { ev.preventDefault(); }          // el foco se queda en la paleta
  });
  lista.addEventListener("mousemove", function (ev) {
    var li = ev.target.closest(".paleta-item");
    if (li && Number(li.dataset.indice) !== activo) { activo = Number(li.dataset.indice); marcar(); }
  });
  lista.addEventListener("click", function (ev) {
    var li = ev.target.closest(".paleta-item");
    if (li) ejecutar(resultados[Number(li.dataset.indice)]);
  });
  fondo.addEventListener("mousedown", function (ev) { if (ev.target === fondo) cerrar(); });

  document.addEventListener("keydown", function (ev) {
    var escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
      ev.preventDefault();
      fondo.hidden ? abrir() : cerrar();
    } else if (ev.key === "/" && !escribiendo && fondo.hidden) {
      ev.preventDefault();
      abrir();
    }
  });

  // El buscador de la barra abre la paleta (conserva lo que ya se haya escrito)
  document.querySelectorAll("[data-paleta-abrir]").forEach(function (disparador) {
    function desdeDisparador(ev) {
      ev.preventDefault();
      abrir(disparador.value || "");
      if (disparador.blur) disparador.blur();
    }
    disparador.addEventListener("focus", desdeDisparador);
    disparador.addEventListener("click", desdeDisparador);
  });
})();
